# Changelog

All notable changes to **SignalRGB Desktop Wallpaper** are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.7-beta] - 2026-06-17

GPU-side perf fix on top of v2.3.6-beta's memory pass.

### Fixed — Widget Float repulsion held N×2 in-flight CSS transitions

The repulsion effect (Widgets Tab → cursor-effect tile "Widget
Float") wrote `--repel-x` / `--repel-y` CSS custom properties on
every widget every 33 ms (30 Hz tick). A separate
`body.fx-repulsion .widget` rule wrapped both vars in a 0.18 s
`cubic-bezier` transition — so every 33 ms rewrite **restarted**
the 180 ms transition.

Net effect: with N widgets the compositor kept 2N CSS animations
in flight at all times, juggling them every frame. Position output
was already smoothed twice (once by the JS dt-based interpolation,
once by the CSS easing); the GPU was paying for an N-widget
animation set that didn't need to exist. Removed the transition;
the 30 Hz JS updates are perceptually smooth on their own. Same
class of regression `gotcha-perf-transitions` warned about (the
v1.0-era grid-zone transition was the original culprit).

### Changed — APP_VERSION + WALLPAPER_VERSION → 2.3.7-beta

Wallpaper bundle re-import IS required.

## [2.3.6-beta] - 2026-06-17

Memory-footprint optimisation: idle full-viewport canvases now
collapse to 1×1 instead of sitting on a ~30 MB backing buffer
each.

### Changed — canvas backing buffers collapse when their effect is off

The wallpaper page hosts four full-viewport canvases:

- `#bars-canvas` — glow grid in canvas-renderer mode
- `#ambient-canvas` — snow / rain / sparks / aurora / storm / …
- `#pixelfx-canvas` — trail / hover-glow / click ripple / water
- `#audioglow-canvas` — pulse / spectrum bars / waveform

Pre-v2.3.6-beta every one of them kept a viewport-sized backing
buffer even when the effect was off. At 5120×1440 × DPR=1 × 4
bytes per pixel that's ~30 MB per canvas → ≈ 100 MB resident per
wallpaper instance even with three of the four idle. Multi-monitor
setups doubled or quadrupled that because each monitor runs its
own WebView2 instance.

Each effect's `stop()` (or `_syncGridCanvasVisibility()`'s
canvas-off branch for `#bars-canvas`) now sets `canvas.width =
canvas.height = 1` after clearing. `start()` already calls
`resize()` to set the canvas back to the full viewport on
re-enable, so the trade-off is one allocation per off→on
transition.

Realistic ceiling on a 2-monitor 5120×1440 setup with three of
the four effects idle: ≈ -150 MB resident RAM.

### Changed — APP_VERSION + WALLPAPER_VERSION → 2.3.6-beta

Wallpaper bundle re-import IS required.

## [2.3.5-beta] - 2026-06-17

Three quick UX fixes on top of v2.3.4-beta after the first round of
real-world feedback.

### Fixed — cursor effects ignored fullscreen pause

The four MouseFx ticks (Liquid Distortion, Chromatic Halo, Spotlight,
Widget Float) were the only rAF loops in the wallpaper page that
didn't short-circuit on `isPaused`. Every other tick (ambient,
audio-glow, pixelfx, parallax, renderFrame) already bailed and the
"wallpaper-resume" event re-armed them on unpause. Now all four
follow the same pattern, and a fresh resume listener kicks them
back to life when fullscreen pause clears.

### Changed — cursor effects moved from Widgets tab to Effects tab

The four cursor distortion effects were in the Widgets card because
that's where they were when the system first shipped, but they alter
the *wallpaper* visuals, not widget layout. Moved into the Effects
card right under the existing Pixelfx (cursor) row where they
conceptually belong.

### Changed — cursor effects: 4 checkboxes → tile grid

The old labeled-checkbox row was bland and didn't surface what each
effect actually does — just an emoji + name. New tile grid: each
tile shows the emoji + name + a one-line description ("Pulls
background pixels with the cursor" / "R/G/B glow around the cursor"
/ "Dims everything outside a cursor disc" / "Widgets ease away from
the cursor on display"). Active tiles get a blue tint + border so
the state reads at a glance. Same four effects, same `mouseEffects`
array persistence — just the UI got a refresh.

### Changed — APP_VERSION + WALLPAPER_VERSION → 2.3.5-beta

Wallpaper bundle re-import IS required.

## [2.3.4-beta] - 2026-06-17

Two-phase atmosphere + UX wave plus a stack of memory-leak fixes
that surfaced during testing. v2.3.3-beta was an intermediate build
that never got cut; v2.3.4-beta folds in everything.

### Added — water-ripple pixelfx mode

A new **Water ripple** option in the cursor pixelfx picker. Each
click spawns three staggered white-blueish rings that grow to
≈ 65 % of the viewport diagonal — reads as an actual water surface
rather than the small tint-coloured ripple `ripple` mode draws.

### Added — Storm ambient preset (rain + lightning)

New **Storm** preset between Rain and Sparks. Rain particles
(reuses the existing rain spawn / step / render) plus a periodic
full-viewport white flash every 6-22 s with ≈ 25 % chance of a
double-pulse mid-fade. Driven by an `after`-style hook in the
ambient renderer so adding similar combined effects later is just
one preset entry.

### Added — weather-reactive ambient overlay

New **Match the real weather** toggle in the Effects tab. When on,
the Weather widget's WMO code drives which ambient preset renders
— rain codes → `rain`, snow codes → `snow`, thunderstorm codes →
`storm`. The user's stored `ambientEffect` setting is never
modified; the override evaporates the moment this is flipped back
off. Requires a configured Weather widget with valid lat/lon.

### Changed — Weather widget redesign

Pre-2.3.3-beta this rendered just the location, temperature and a
textual condition. New layout: a condition-dependent SVG icon (sun
/ partly cloudy / cloud / rain / snow / storm / fog) left, location
+ condition in the middle, big temperature right. Underneath:
apparent temperature ("Real Feel"), daily high / low row with arrow
glyphs, and a small extras row with precipitation probability,
humidity, wind speed. `fetchWeather` now requests the additional
fields from Open-Meteo in the same call.

### Added — widget skin system

`WIDGET_REGISTRY[type].skins.<id>` registers alternative
`markup()` + `render(rec)` pairs for an existing widget type. The
widget's `opts.skin` (default `"default"`) picks which one runs;
swapping it at runtime regenerates the widget body and swaps a
`widget-skin-<id>` class on the widget element so the matching CSS
takes effect. Weather ships three skins as the proof-of-concept
set:

- `default` — the redesigned 2.3.4-beta layout above
- `compact` — single icon + temperature row, location + condition
  combined underneath, no extras
- `hexagon` — central hexagonal tile (CSS clip-path polygon) holding
  the icon + temp + condition, small extras row below

Picked from the widget config modal's **Skin** dropdown. The
Configurator hardcodes the catalog for now; the bridge also
serves it at `GET /widgets/skins[?type=weather]` so a future
iteration can move to dynamic discovery. New
[Widget skins documentation](widget-skins.md) walks through the
architecture and how to add another skin. Plugins (= entirely new
widget *types*) remain a separate mechanism.

### Fixed — Liquid Ripple was leaking ~1 MB/s during mouse motion

The SVG `feDisplacementMap` source was being updated every frame
via `mapCanvas.toDataURL()` + `feImg.setAttribute("href", ...)`.
Chromium's SVG filter pipeline cached a decoded bitmap per unique
data: URL and never released them (data: URLs can't be revoked),
so steady mouse motion produced one new retained value per frame
≈ ≈ 1 GB after 15 min. Now:

- Stays on `toDataURL` (synchronous, no rAF stall — an interim
  `toBlob` + `URL.createObjectURL` + `revokeObjectURL` repair
  eliminated the leak but stuttered the visible displacement
  because `toBlob` is async).
- Tracks an idle-frame counter; after ≈ 2 s of no cursor motion
  *and* no in-progress decay we stop encoding + poking `feImage`.
  The decay loop keeps running in the canvas so when the next
  ripple-worthy event happens we resume from the right state, but
  the SVG paint pipeline isn't fed fresh data: URLs in the idle
  window — which was where the steady-state RAM growth was
  coming from.

Net: leak is limited to the time the user actively moves the
mouse with the effect on. Idle = flat memory.

### Fixed — Magnify Spotlight had the same leak pattern

`o.style.background = "radial-gradient(circle 180px at " +
_cursorX + "px " + _cursorY + "px, ...)"` every frame produced a
fresh `CSSImageValue` per unique cursor position that Chromium's
paint engine retained. Refactored to define the gradient once via
`cssText` using `var(--fx-sl-x)` / `var(--fx-sl-y)`, and the tick
only updates the two CSS custom properties. Same approach the
Chromatic Aberration effect already used — Spotlight had drifted
out of pattern.

### Changed — APP_VERSION + WALLPAPER_VERSION → 2.3.4-beta

`wallpaper/index.html` shipped substantial changes (storm preset,
water-ripple mode, weather-reactive override, redesigned weather
widget, skin system + 3 skins, two memory-leak fixes). Lively /
Wallpaper Engine **re-import is required** for any of these to
land — Lively caches each imported zip in a random-hash folder
and never re-reads the source, see
[gotcha → "Updated wallpaper but Lively still shows the old version"](troubleshooting.md).

## [2.3.2-beta] - 2026-06-15

Targeted follow-up to v2.3.1-beta.

### Fixed — library went blank after deleting the last item of an active tag / source filter

`_libraryRevalidateFilters` only ran on initial page load. If the
user filtered to a specific tag or source chip and then deleted
every item that matched (single delete via the right-click menu OR
the new bulk-delete), the JS-memory filter still pointed at the
now-orphan value and `_itemPassesFilter` rejected every remaining
item. Library tab rendered with just the "Bild hinzufügen" tile —
the rest of the catalogue was fine on disk and on the wire, just
invisible.

The validator now runs after every `refreshLibrary()` too (which
is the post-delete + post-pack-install / -uninstall path), so any
orphan tag / source gets cleared immediately and the grid never
goes blank because of an in-memory filter that survived a delete.

## [2.3.1-beta] - 2026-06-15

Iteration on the v2.3.0-beta pack browser plus a stack of UX fixes
that surfaced under heavy testing. v2.3.0-beta.1 and -beta.2 tags
were spun up during the iteration and never released; v2.3.1-beta
folds everything together.

### Added — preview thumbnail per pack

Pack tiles in the Library tab's pack browser now show a 96×54
preview of the pack's first image alongside the name + description.
Sourced from
`delido.github.io/signalrgb-wallpaper/library-packs-previews/<pack_id>.webp`,
URL constructible from the pack id so no manifest bloat. Missing
previews silently fall back to the solid placeholder.

`installer/build_packs.py` now copies the preview WebPs into
`docs/library-packs-previews/` on every build so the docs site
stays in sync with the published ZIPs.

### Added — pack uninstall

Installed pack tiles show an **Uninstall** button next to Load /
Update. Confirms first, then walks `library.json`, removes every
file (+ thumb + 4K siblings) tagged with that pack, rebuilds the
catalogue. User-uploaded items without pack metadata stay
untouched. Runs in the executor.

### Added — library multi-select with bulk delete

New **Auswahl** toggle in the library toolbar puts the grid into
selection mode. Tiles toggle on click, get a checkmark badge, and
a bulk-action bar (**Select all** / **Clear** / **Delete selected**)
appears above the grid. Bulk delete loops
`DELETE /library/<name>` and reports counts.

### Added — Bildschirme picker back in the header

The screen-count picker (1/2/3/4) moved out of the System tab card
and back into the header bar, next to **Vorschau** / **Tour** /
**Open Builder…**. Feedback was that the screen count is changed
often enough that it belongs at the top, not buried in System.

### Changed — Voreinstellungen card moved to the Look tab

The presets card lived in System through v2.3.0-beta and migrated
through Widgets in -beta.1; final home is **Look**. That's where the
per-screen background + glow + dim state is configured, so "save
my current setup" naturally belongs there.

Slot row redesigned: 80×45 thumb → 160×90 (the canvas's native
render size, no down-clamp), grid layout with name + summary
stacked next to the thumb instead of competing for flex space,
dashed border on empty slots.

### Fixed — pack browser only showed the last-installed pack as Installed

The catalogue rebuild was preserving `pack_id` but stripping
`pack_version`, and the installed-state check needed both. Now
both round-trip through every rebuild so multiple packs can be
installed simultaneously and the UI shows each one's badge
correctly.

### Fixed — cycle scheduler crashed on fullscreen pause edges

`CycleScheduler._tick` called `bridge.get_screen_count()` (public
name) but `BridgeRuntime` exposes `_get_screen_count()`
(underscored). Every 30 s, if the cycle path got touched (e.g.
during a fullscreen-pause transition), the log lit up with
`[cycle] tick crashed: 'BridgeRuntime' object has no attribute
'get_screen_count'`. Wired to the underscored member.

### Fixed — preset thumbnails were always black

`generatePresetThumbnail` fetched `/screen/{n}/background` to paint
the BG layer, but that endpoint is POST-only (upload). 404 silently
meant the BG was skipped and every preset thumb came out as a
black widget grid. Now reads `settings.bgImage` directly — same
source the wallpaper page renders from — and routes absolute paths
through the `/image` proxy.

### Fixed — assorted multi-select edges

- Bulk-action bar showed `{n} ausgewählt` literally on first
  Library open because the i18n pass painted the raw placeholder
  before `_libUpdateBulkBar` ever ran. Removed `data-i18n` from
  the count span; JS owns the text fully.
- Bar was visible on initial Library open before any selection —
  `display: flex` won against the HTML `hidden` attribute. Added
  `.lib-bulk-bar[hidden] { display: none !important; }`.
- Per-tile delete (×) overlapped with the new selection checkbox
  in the top-right corner. Hidden while `body.lib-selecting` is
  active; the bulk-delete bar handles deletion in that mode.
- **Alle auswählen** selected every catalogue entry regardless of
  the active filter. Now respects `_itemPassesFilter` so the
  selection matches what's visible on screen — picking "aurora"
  as the source then Select-all selects 9 items, not all 66.

### Fixed — library appeared empty after bulk delete if a filter pointed at a deleted pack

`cfg.libraryPack` in localStorage persisted across the bulk
deletion. If the user had filtered by an installed pack
(e.g. "aurora") then bulk-deleted everything in that pack, on
next reload the catalogue still had ~20 entries but
`_itemPassesFilter` dropped them all because nothing carried
`pack=aurora` anymore. Library tab rendered with just the "Bild
hinzufügen" tile — no broken-state hint.

On load now: any persisted `_libraryPack` / `_libraryTag` that
doesn't match anything in the freshly-loaded catalogue is
silently reset (and the localStorage entry cleared). The grid
shows everything; the user picks a new filter consciously.

### Fixed — Bildschirme card in System tab was an empty stub

After the picker moved to the header in this release, the System
tab's old screen-count card was left rendering just the title +
hint with no buttons underneath — looked broken. Card is now a
hidden DOM stub: `#card-screens` still resolves for selector
lookups but the user never sees it.

### Fixed — ripples ambient preview threw IndexSizeError every frame

The ripples particle's `step` callback could briefly produce a
negative radius on the first frame after spawn (small backward `dt`
during tab-visibility transitions). `ctx.arc` rejects negative
radii with `IndexSizeError` and the whole render loop unwound. Now
clamped to `Math.max(0, p.r)` at render time.

### Changed — APP_VERSION → 2.3.1-beta

`WALLPAPER_VERSION` unchanged (still 2.2.0). Bridge + Configurator
+ docs only. Lively / Wallpaper Engine re-import NOT required.

## [2.3.0-beta] - 2026-06-15

In-app wallpaper-pack browser is back, three years (well, three releases)
after v2.0.1 ripped it out under Defender FP pressure. The
v2.2.x mitigations made it safe to bring back; the new flow is
also less malware-shaped than what v2.0.0 shipped.

### Added — `📦 Wallpaper packs (download)` section in the Library tab

Open the section, the bridge fetches a manifest from this docs site
(GitHub Pages,
[`library-packs.json`](https://delido.github.io/signalrgb-wallpaper/library-packs.json))
listing every available pack. Each tile shows name, description,
image count, total download size, and an action button. Click
**Load** and the bridge:

1. Downloads the pack ZIP from the
   [`library-packs-v1`](https://github.com/Delido/signalrgb-wallpaper/releases/tag/library-packs-v1)
   GitHub release.
2. SHA-256-verifies the downloaded bytes against the digest in the
   manifest. Mismatch → install aborts, partial ZIP deleted.
3. Walks every ZIP entry before extracting anything and refuses
   any non-image entry. The extracted footprint is provably
   `.webp / .png / .jpg / .gif / .bmp / .avif` only — no
   executable / script content from a pack can ever land on disk.
4. Extracts into `%LOCALAPPDATA%\SignalRGBWallpaper\library\`,
   stamps each new entry with `pack` + `pack_version`, and rebuilds
   the catalogue.

All steps run server-side in the bridge's executor pool — the
Configurator stays responsive throughout. Per-pack `Installed` /
`Update available (vN → vM)` badges read from the stamped
metadata, so version drift between manifest and what's on disk
is visible at a glance.

### Why this is safer than v2.0.0's pack downloader

The v2.0.0 pack downloader tripped Windows Defender's ML heuristic
as `Wacatac.B!ml`. The two strongest signals it was catching are
both gone in v2.3.0-beta:

- **Bridge install location.** v2.0.0's bridge lived in
  `%LOCALAPPDATA%\Programs\SignalRGBWallpaper\` — the classic
  "unsigned EXE in user-writable persistence path" pattern. v2.2.1
  moved the bridge to `C:\Program Files\SignalRGBWallpaper\`
  (admin-only ACL); the pack downloader is no longer running from
  a malware-shaped location.
- **What a pack can drop on disk.** v2.0.0 extracted whatever was
  in the ZIP. The new path enforces an image-extension whitelist
  on every entry before the first byte gets unpacked — so the
  extracted footprint can be classified as "image data only", much
  harder for the ML model to score as loader-shaped than a generic
  `zipfile.extractall` would have been.

Plus user-triggered (the download only runs when you click **Load**
on a specific pack — no background polling), SHA-256 verification
(matches the v2.2.2 updater pattern), and the manifest moved from
`raw.githubusercontent.com` to GitHub Pages (looks like normal
docs traffic to AV / firewall heuristics).

### Changed — APP_VERSION → 2.3.0-beta

`WALLPAPER_VERSION` unchanged (still 2.2.0). Bridge + Configurator
only — no wallpaper bundle code touched. Lively / Wallpaper Engine
re-import NOT required.

## [2.2.2] - 2026-06-15

Internal audit sweep. Nine items found, all nine fixed. Three classes
of problem dominated: event-loop blockers (same shape as the v2.2.1
auto-cut / transform hotfix, just on three more endpoints),
data-integrity holes around `library.json`, and an open path through
the auto-updater that could have shipped a swapped installer.

### Fixed — supply-chain check on the auto-updater

The tray's "Download and install update" path used to fetch the
release asset and run it without any integrity check. A compromised
GitHub Release upload (stolen workflow token, account hijack) could
silently replace the installer with anything; every user who clicked
"Update" would have run it. Now `build.ps1` emits a
`SignalRGBWallpaperSetup-<version>.exe.sha256` sidecar alongside
the installer, the release upload carries both, and the bridge's
updater downloads both, SHA-256s the local file, and refuses to
launch on mismatch or missing sidecar. Attackers now have to tamper
the .exe AND the .sha256 together AND get both past the release
upload — strictly more work than swapping the exe alone.

### Fixed — `library.json` could be corrupted by a crash mid-write

`_library_rebuild_catalogue`, `_library_update_item`, and
`_library_apply_order` all wrote the catalogue with a direct
`write_text(...)` — a power loss or OOM between the truncate and the
final write would leave an empty / half-written file. Next bridge
start would either fail to parse it or surface an empty Library tab.
All three helpers now use the same `tmp + rename` pattern
`save_config` already used for `config.json`; the rename is atomic
on every modern filesystem so a concurrent reader sees either the
old file or the new, never a torn one.

### Fixed — silent data loss when uploads + pins raced (regression from v2.2.1)

v2.2.0's hotfix moved the heavy auto-cut + WebP-transform work into
a thread executor, which was the right call for unblocking the
event loop. The unforeseen consequence: that thread and the asyncio
main loop could now both hit `library.json` simultaneously — a user
pinning an entry while an auto-cut upload finishes would race, and
whichever thread wrote last would silently overwrite the other's
mutation. Added a process-wide `threading.RLock` (`_LIBRARY_LOCK`)
that every catalogue mutation must hold; the read-modify-write
sequence in `_library_update_item` now runs end-to-end under the
lock so pin / tag / category / reorder updates are serialised
against rebuilds.

### Fixed — three more endpoints blocked the event loop

Same root cause and same fix as v2.2.1's autocut + transform
endpoints. The remaining offenders surfaced during a full audit
pass:

- `POST /library/thumb` — synchronous `_library_rebuild_catalogue`
  call after writing the thumbnail. Now offloaded to the executor.
- `DELETE /library/<name>` — same. Plus the handler picked up
  three validation hardenings the GET sibling already had:
  URL-decoding of `%XX` escapes (so a delete on a filename with
  spaces no longer 404s), the `.startswith(".")` rejection, and
  the resolve-and-`relative_to(library_dir())` check that closes a
  theoretical symlink-escape vector.
- `POST /backup/restore` — ZIP extraction + per-file writes (up to
  100 MB) + the full rebuild. Used to freeze the bridge for 5-30 s;
  every WS ping and Configurator request stalled. Same executor
  fix.

### Fixed — slow WebSocket clients leaked memory forever

`broadcast_frame`, `push_settings`, `push_pause`, `push_widgets`,
and `push_reload_all` each contained the same backpressure check
— if a client's `StreamWriter` buffer exceeded the 256 KiB cap,
skip the write. Right idea, but there was no upper bound: a
backgrounded browser tab that throttled its event loop could stay
over the limit indefinitely and we'd keep it in
`clients_by_screen` forever, leaking ~256 KiB per client per
broadcast pulse. Lifted the check into
`Broadcaster._client_should_skip()` which now tracks consecutive
skips per writer and force-closes after 200 of them
(≈ 6 s at 30 Hz). Healthy clients reset the counter on every
successful write. `remove()` also drops the counter so the dict
itself doesn't grow over a long uptime.

### Changed — APP_VERSION → 2.2.2

`WALLPAPER_VERSION` unchanged (still 2.2.0). No wallpaper-bundle
code touched this release — bridge + installer + build script only.
Lively / Wallpaper Engine re-import NOT required.

## [2.2.1] - 2026-06-14

Anti-Defender-FP hotfix: reshapes the binary + install location so
Windows Defender's `Trojan:Win32/Wacatac.C!ml` ML heuristic stops
matching on every fresh install.

### Changed — install moved to `C:\Program Files\SignalRGBWallpaper`

Pre-2.2.1 installed per-user into `%LOCALAPPDATA%\Programs\…`. That
path is **the** classic "unsigned EXE + user-writable persistence
location" malware pattern — Defender's ML weights it heavily.
Discord/Slack/Chrome get away with it because they're signed; we're
not, so we move to `Program Files` (admin-only ACL) instead.

Trade-off: UAC prompt on install + update. Per-user data
(`%LOCALAPPDATA%\SignalRGBWallpaper\`) is unchanged.

The installer now wipes the legacy location automatically:

- Stops the running `SignalRGBBridge.exe` from `%LOCALAPPDATA%\Programs`
- Deletes the legacy install directory
- Deletes the per-user Start-Menu folder + the early-2.2.1
  `%PROGRAMDATA%` Start-Menu folder (Windows 11 sometimes doesn't
  index those live — `AlwaysUsePersonalGroup=yes` keeps the new
  shortcuts in the per-user Start Menu where Windows always sees
  them)
- Removes the legacy HKCU `Uninstall\…_is1` registry entry
- Rewrites HKCU `Run\SignalRGBWallpaperBridge` autostart with the
  new path

### Changed — `SignalRGBBridge.exe`: 5.9 MB → 0.56 MB

PyInstaller was packing the application bytecode into a
zlib-compressed PYZ archive and **appending it to the EXE**. That
made the EXE a small bootloader followed by ~5 MB of high-entropy
compressed data — textbook crypter / packer signature, exactly
what Defender's ML scores as a Wacatac-class loader.

`-d noarchive` keeps the bytecode as individual `.pyc` files in
`_internal/` instead. EXE shrinks to a 0.56 MB pure bootloader;
nothing high-entropy lives inside it. `--noupx` is added defensively
in case a future build environment has UPX on PATH (currently a
no-op since UPX isn't installed on the standard build env).

### Fixed — `reimport-wallpaper-bundles.ps1` CLI default path

The script's `-AppDir` parameter defaulted to
`%LOCALAPPDATA%\Programs\SignalRGBWallpaperBridge` — wrong location
AND a bonus "Bridge" suffix that never matched anything. Bridge.py
always passes the real path so this was a latent bug, but anyone
running the script directly from a shell hit a "folder not found"
silently. Now defaults to `%ProgramFiles%\SignalRGBWallpaper`.

### Known UX regression — silent update prompts for UAC

The tray's auto-update flow downloads + runs the new installer
silently. With `PrivilegesRequired=admin`, Inno raises a UAC
consent dialog regardless of `/SILENT`. Accept the prompt to let
the update proceed — it then installs unattended. No way around
this short of code-signing + EV trust reputation.

## [2.2.0] - 2026-06-14

Big UX pass on the Configurator + Builder, plus a hotfix for a
freeze that hit Library uploads / rotate-flip on multi-MB images.

### Added — Configurator vertical sidebar + floating preview

The section nav moved from a horizontal tab row above the cards
into a sticky vertical sidebar. A new **📺 Vorschau** toggle in the
header pops a floating live preview of the wallpaper (its own
iframe instance — no DOM moves, doesn't fight the Widgets-tab
inline preview).

Look-tab additions:

- **Bildschirm-Layout** card replaces the per-tab ⚙ gear popover
  (gear hidden). Span / mirror / reset live in the card directly.
- Current-background thumbnail tile with click → Library tab.

### Added — Library tab context menu

Right-click on any library tile now shows apply / rotate / mirror /
pin / rename / duplicate / delete. Rotate + flip operations run
server-side via PIL (`POST /library/transform`), apply to the
main file + thumb + 4K siblings together, and survive bridge
restarts.

### Added — Integrations sub-blocks

The big System card on the Integrations tab now keeps `System`
expanded by default and collapses each integration (OpenRGB
output, OpenRGB SDK server, per-screen colour source, sACN /
E1.31, MQTT, REST API, plugins) into its own `<details>` block.

### Added — Builder: Apply ▾ from the canvas + Wall sub-region crop

- New **Apply ▾** button in the canvas toolbar opens a dialog
  with one entry per bridge screen (stretch or span-split). Skips
  the full Monitor-Wall flow when you just have one image.
- Wall tiles for span screens now render their actual sub-region
  of the bridge background (`background-position` + `-size` crop)
  instead of repeating the full image in every tile.
- Drag-into-canvas always lands in the editor (the
  *Editor / split-across-span* popup is gone).
- "Bild auswählen…" button is visible in Simple mode too.

### Added — Header logo + favicon

Inline SVG (monitor + 5 RGB pads, mirroring the tray icon) in
both the Configurator + Builder header bars, plus the same image
as inline-data-URI favicon for both pages.

### Fixed — Configurator froze for ~1 min on Library uploads with Auto-Cut

The PIL alpha-cut + WebP encode + `_library_rebuild_catalogue`
all ran synchronously inside the async HTTP handler — a 4K
upload blocked every other Configurator / WebSocket / wallpaper
request for the duration. Pushed both into the default executor
and dropped the WebP encoder from `method=6` → `method=4`
(~5× faster, near-identical quality for wallpapers).

### Fixed — Library rotate / flip silently failed

Same root cause as the Auto-Cut freeze, multiplied by three
because rotate/flip re-encodes Main + Thumb + 4K variants per
click. The bridge eventually answered, but the CEF fetch timed
out first → JS toast surfaced as `Transform failed`. Same fix:
move into executor, drop WebP method.

### Changed — APP_VERSION + WALLPAPER_VERSION → 2.2.0

Wallpaper bundle re-import IS required (`wallpaper/index.html`
shipped the in-page widget picker removal in this release).

## [1.7.4-beta] - 2026-06-06

### Fixed — library filter chips stayed English on first paint

The Background-tab library strip's filter chips (`All / Backgrounds /
Templates / Pinned`) are rendered into dynamically-built DOM inside
`renderLibraryStrip()`, which uses `t()` for the labels. The Configurator's
language detection runs **after** the WebSocket settings push from the
bridge — meaning if the library catalogue loaded first (the
`/library/list` fetch resolves quickly), the chips got their boot-time
English labels baked in.

`setLanguage()` then called `renderAll()` to refresh dynamic strings, but
`renderAll()` didn't include `renderLibraryStrip()` — every other dynamic
surface picked up the language switch, the library chips alone stayed
in their original language until the user clicked anything (which
triggered a re-render and surfaced the German labels).

Added `renderLibraryStrip()` to `renderAll()`'s tail so the language
switch refreshes the chips too. Guarded against the rare case where
`renderAll()` runs before the library has finished loading.

### Changed — APP_VERSION → 1.7.4-beta

WALLPAPER_VERSION unchanged. configurator.html only; Lively / Wallpaper
Engine re-import not required.

## [1.7.3-beta] - 2026-06-06

### Fixed — Wormhole ambient cohort die-off was jerky

Every particle hit the 3.0 s hard-lifespan cap at the same time it
was spawned in a burst — after the initial fill, or after a
cursor-move triggered mass respawn, the population was effectively
single-cohort and died synchronously 3 seconds later → visible
mass disappear + instant fresh respawn = "abgehakt" / stuttering.

Two-part fix:

- **Stagger lifespans at spawn**. New particles start at
  `life = -Math.random() * 1.8` instead of `life = 0`, so each
  particle's effective max-life is between 3.0 s and 4.8 s. The
  cohort's death timing is spread across a ~2 s window from spawn
  one onward.
- **End-of-life alpha fade**. The render path now reads `maxLife`
  off the particle and ramps alpha linearly to zero over the last
  0.4 s of life. Particles dissolve smoothly into the swarm instead
  of popping out.

Both also apply to the inner-consume / outer-escape kill paths
(`dist < 24`, `dist > hypot(w,h)*0.5`) so all three death triggers
get the same gradual fade-out.

### Added — cursor-aware ambient effects get a mouse badge

The ambient-effect tile picker now renders a small mouse-pointer
SVG badge in the top-right corner of any preset whose particle
dynamics use the live cursor position as an anchor. Currently
that's just Wormhole — but the `CURSOR_AWARE_AMBIENT` Set in
configurator.html keeps the door open for future cursor-driven
presets (constellation-follows-cursor, fireflies-attracted, …).

Hover tooltip surfaces the same info as text
(EN: "follows the mouse cursor" / DE: "folgt dem Mauszeiger").

### Changed — APP_VERSION + WALLPAPER_VERSION → 1.7.3-beta

`wallpaper/index.html` gained the Wormhole lifespan staggering + the
end-of-life fade, so the bundle needs to re-load. Lively /
Wallpaper Engine re-import recommended (auto-reimport runs on the
new bridge's first startup so most users don't need to touch
anything).

## [1.7.2-beta] - 2026-06-06

The **cmd-free update flow** beta. Local-only staging — not
released yet. Reworks the auto-update relaunch path to fix
"installer ran but new bridge never appeared" reports.

### Fixed — auto-update sometimes left the user without a running bridge

The old flow had the dying bridge spawn a detached
`cmd /c timeout /t 40 /nobreak && start "" "<exe>"` to relaunch
the newly-installed bridge ~40 s later. That spawned a visible
cmd window with a countdown — which on user setups was getting
killed by AV / window-manager edge cases / accidental close
before the timeout fired. End result: installer ran, replaced
the exe, but no new bridge process appeared. User had to
manually start the bridge from the Start menu.

Reworked: the Inno `[Run]` entry now launches the new bridge
directly via the `shellexec` flag — which routes through
`ShellExecuteEx`, the canonical "as if launched from Explorer"
path. That's the same launch mechanism `download_and_install`
in bridge.py already uses successfully via ctypes
`ShellExecuteW`. Fresh user-context token + standard shell DLL
search path → no LoadLibrary regression (which was the v1.2.11
reason the deferred-cmd workaround existed in the first place).

`autostart` re-added to `MERGETASKS` in `download_and_install`
so the `[Run]` entry fires under `/SILENT` install too. The
40-second cmd-timeout block is gone; the bridge just exits
after spawning the installer + dropping the `.pending-reimport`
marker.

End result: no cmd window flash, no fragile timeout, no
"installer ran but bridge missing" failure mode.

### Changed — APP_VERSION → 1.7.2-beta

WALLPAPER_VERSION unchanged at 1.7.0. No wallpaper/ side changes.
Lively / Wallpaper Engine re-import NOT required.

## [1.7.1] - 2026-06-06

The **encoding hotfix** patch. First fresh-install report from a
German Windows user surfaced a regression in the installer-bundled
PowerShell scripts.

### Fixed — installer PS1 scripts unparseable on cp1252 systems

`reimport-wallpaper-bundles.ps1` (and every other `.ps1` in the
installer) had been saved as UTF-8 *without* BOM. Windows
PowerShell 5.1 — still the default on Windows 10 / 11 — reads
BOM-less files using the system codepage. On a German install
that's cp1252, so any multi-byte UTF-8 sequence (em-dashes,
bullets, …) gets mangled into mojibake. The mangled bytes broke
quote / parenthesis balance and the script failed at parse time:

```text
Schließende ")" fehlt in einem Ausdruck.
+ ... ely CLI: $livelyExe (process detected ƒ?" running re-import)" "Green"
```

User saw a tray notification with exit code 1, no fallback,
wallpaper bundles never reached Lively / Wallpaper Engine.

Fixed by prepending a UTF-8 BOM (`EF BB BF`) to all six
installer scripts. With a BOM present PowerShell 5.1 picks UTF-8
reliably regardless of system locale, so the same script binary
now parses cleanly on de-DE / en-US / fr-FR / any other Windows
codepage. Verified against the actual PowerShell parser
(`[System.Management.Automation.Language.Parser]::ParseFile`)
on each script — zero errors.

## [1.7.0] - 2026-06-03

The **stable cut** of everything that landed between v1.3.0 (last
stable) and the v1.6.5-beta head. Three months of beta cycles
collapsed into one promote-to-stable. Read the v1.4 → v1.6.5-beta
sections below for the line-by-line history; this entry just calls
out the headline groups.

### Added — LED ecosystem (v1.4 → v1.5)

- **OpenRGB output channel** (v1.4): mirror the wallpaper glow onto
  real OpenRGB devices (RAM / fans / keyboards / strips).
- **Spatial mapping** (v1.5): per-device `(x, y)` point or line
  endpoints on the source screen so multi-LED devices show a
  gradient instead of one averaged colour.
- **Per-screen source picker** (v1.5): each screen can independently
  take its glow from SignalRGB UDP, OpenRGB (polled), or sACN /
  E1.31 multicast.
- **sACN / E1.31 outbound emitter** (v1.5): per-screen universe
  publishing on the standard multicast group — receivers like
  xLights, QLC+, Hyperion can drive lighting from the wallpaper.
- **HA / MQTT bridge** (v1.5): publishes per-screen state with HA
  Discovery payloads so Home Assistant auto-creates entities for
  preset / pause / glow / background per screen.
- **OpenRGB SDK server** (v1.6.2): inverse of the output channel —
  the bridge exposes itself to the OpenRGB GUI as virtual matrix
  devices, one per screen. 6 built-in modes (Direct / Static /
  Breathing / Rainbow / Rainbow Wave / Color Wave) with a
  bridge-side 30 Hz effect engine. See
  [docs/openrgb-sdk-server.md](docs/openrgb-sdk-server.md).

### Added — API surface (v1.5)

- **REST API at `/api/v1/*`** — info, screens, settings, preset
  apply, pause, profiles, plugins. Per-install bearer token with
  loopback bypass. Hand-written OpenAPI 3.1 spec at
  `/api/openapi.json` + a human-readable companion at
  [docs/api.md](docs/api.md).
- **Plugin API for 3rd-party widgets** (v1.5): sandboxed-iframe
  runtime + `manifest.json` discovery + postMessage IPC. Author
  contract at [docs/plugin-api.md](docs/plugin-api.md).
- **Generic HTTP widget** (v1.5): URL + refresh interval + mustache
  templating covers Discord / stocks / RSS / crypto / arbitrary
  REST with one widget type.

### Added — Visual polish (v1.6)

- **Widget Theme System** (v1.6.0 → v1.6.1): 11 colour-palette +
  typography pairings (Default / Dracula / Nord / Tokyo Night /
  Catppuccin / Solarized / Vintage CRT / Light / Gruvbox / Rose
  Pine / Cyberpunk Neon). Swatch-grid picker, instant pulse
  feedback on switch. CSS-variable based — independent of the
  v1.1 tile style.
- **Mouse-driven distortion effects** (v1.6.0): four stackable
  cursor-position-driven effects — Widget Repulsion, Chromatic
  Aberration, Magnify Spotlight, Liquid Ripple
  (`feDisplacementMap`).
- **Wormhole ambient preset** (v1.6.1): cursor-aware accretion-disc
  particle system with inverse-square gravity + tangential swirl.
- **Library category system** (v1.6.1): per-entry
  `background` / `template` / `both` so auto-cycle never picks
  Builder source images. Filter chips + tile category badges +
  right-click recategorise.

### Added — UX overhaul (v1.6.1)

- **Configurator R2** — 9 settings cards split across 5
  horizontal tabs (Look / Effects / Widgets / Integrations /
  System). Sticky tab row, last-active tab persisted, `#tab=KEY`
  deep-links. Tour walks each tab.
- **Library grid layout** — filter chips out of the strip, CSS
  Grid with auto-fill tiles, dashed `+ Add image` in-grid.
- **Preset thumbnails** — each filled slot button renders an
  80×45 client-side miniature.
- **`effectQuality` per-screen** (v1.6.3): performance / balanced /
  quality bucket controls ambient + pixelfx + audio-glow canvas
  backing resolution + DPR + frame cap. Default `performance`.

### Performance — GPU sweep (v1.6.1)

User report of ~19 % sustained GPU under Snow on 5120×1440 →
audit found every effect rAF chain running uncapped at native
60 Hz + DPR ×2 backing buffers on full-viewport canvases. Sweep
fixes documented in
[memory `gotcha-uncapped-raf-dpr`]. End state on 5120×1440:
Snow + 3 widgets + glow at ~5-7 % (was ~19 %); idle = 0 %.

### Fixed — picked up along the way

Roughly two dozen smaller fixes during the beta cycle. The big
ones:

- Preset `Save/Apply` audit caught `widgetTheme` + `mouseEffects`
  silently dropped (added in v1.6.0 but missing from
  `PRESET_SNAPSHOT_KEYS`).
- Tab-init race (Effects tile previews XOR widget Layout-Vorschau
  depending on which tab restored from localStorage).
- Audio-glow uncapped at native rAF rate burning ~10 % GPU
  (fixed by the GPU sweep above).
- OpenRGB SDK descriptor format took five hotfix iterations
  against the real OpenRGB GUI before connect → enumerate →
  mode-pick worked end to end. Documented for future
  maintainers in the v1.6.2-beta CHANGELOG block.

### Changed — APP_VERSION + WALLPAPER_VERSION → 1.7.0

`wallpaper/index.html` is 1,203 lines heavier than v1.3.0 with
themes / mouse-fx / wormhole / R2 layout / quality picker / GPU
sweep. **Lively + Wallpaper Engine re-import required** for
existing users.

## [1.6.5-beta] - 2026-06-03

The **audit follow-up #2** beta. Five findings from the v1.6.4-beta
review.

### Fixed — `reload()` race fully closed

v1.6.4-beta added a `prev.join(timeout=0.2)` in `stop()` to keep
the old + new engine threads from running in parallel. But on
timeout, the old thread was still alive when `start()` cleared
the shared `_engine_stop` flag → the old thread saw `stop=False`
on its next tick and lived forever. Each generation now owns its
own `Event`, passed in via `_effect_loop(stop_evt)`. Old
generations hold the old Event in their closure; `start()`
allocates a fresh one and never reaches into the old.

### Fixed — Color Wave centred on red when colour is grayscale

`_rgb_to_hue` returns 0 for any grayscale input. `dev.color`
defaults to white (255, 255, 255) on a new GUI connection, so
Color Wave's ±0.15-hue wave centred around hue 0 → all red until
the user picked an explicit colour. Now a grayscale-base fallback
nudges base_h to 0.55 (calm cyan-blue) so the wave reads as
"colour wave" rather than "red wave" out of the box.

### Fixed — direction convention inverted for wave modes

OpenRGB convention: LEFT (d=0) increments the hue offset → pattern
visually moves leftward. RIGHT decrements → moves rightward. My
previous wiring had this backwards — picking LEFT in the GUI
moved the wave rightward and vice versa. Swapped the `reverse`
bitset to match OpenRGB.

### Changed — i18n style consistency for system-action toasts

`system.check_updates_now` + `system.open_releases` shipped with a
gerund-with-ellipsis style ("Checking…" / "Opening…") that
clashed with the existing infinitive/button-label style
(`system.reload_config` = "Reload config from disk"). Rephrased
to match the rest.

### Changed — visual separators between `card-system` sub-sections

Auto-expanding `card-system` in v1.6.4-beta surfaced the System
card's full 7-block content stack (OpenRGB output / SDK server /
Sources / sACN / MQTT / REST / Plugins) at once with no visual
separation — sub-sections bled into each other and the user
couldn't tell where one ended and the next began. Added
panel-tinted h3 bars + border-tops so each sub-block reads as a
self-contained unit without forcing the user back to manual
collapse.

## [1.6.4-beta] - 2026-06-03

The **audit follow-up** beta. A sweep of correctness + UX +
security findings from the v1.6.3-beta review.

### Fixed — section-tabs row not sticky on scroll

The `#section-tabs` row used `top: 84px`, which sat *inside* the
`.tabs` (screen-picker) sticky band — when scrolling, the upper
slice of section-tabs slipped under the screen-picker and the
tab labels visibly overlapped page content. Header (~46 px) +
screen-tabs (~50 px) ≈ 96 px, so 100 clears both with a small
buffer.

### Fixed — `Integrations` + `System` tab cards collapsed by default

The R2 IA split the 9 cards across 5 tabs, but four cards
(`card-presets`, `card-profiles`, `card-backup`, `card-system`)
kept their pre-R2 `collapsed` class. With each tab now showing
1–3 cards instead of all 9, manual expansion was just friction.
Removed the initial `collapsed` class from those four; users
can still collapse them manually.

### Fixed — missing `system.check_updates_now` + `system.open_releases` i18n

Clicking "Jetzt prüfen" / "Releases-Seite öffnen" in the System
tab raised a toast with the raw i18n key as visible text. Added
both translations (EN + DE).

### Fixed — `dev.direction` from `UpdateMode` was unused

OpenRGB GUI's direction picker on Rainbow Wave + Color Wave did
nothing — the picked direction was parsed into `dev.direction`
but the render code only ever swept LR. Fixed: render now
respects all four directions (LEFT / RIGHT / UP / DOWN), with
vertical directions iterating by row and reverse directions
flipping the time sign so the sweep flows the picked way. Both
wave modes also gain the `HAS_DIRECTION_UD` flag so the GUI
offers up/down picks alongside left/right.

### Fixed — SDK server default host exposed LAN

`openrgbSdkServer.host` defaulted to `0.0.0.0`, which bound the
listen socket on every NIC — anyone on the same LAN could
enumerate + drive the wallpaper. OpenRGB itself ships with the
`127.0.0.1` default for the same reason. Changed default to
loopback; LAN-aware setups (driving from another machine) can
flip back to `0.0.0.0` or a specific NIC explicitly.

### Fixed — `reload()` race between old + new effect engine threads

A fast `reload()` could briefly run two engine daemons in parallel
because `start()` cleared `_engine_stop` before the previous
loop's wait returned. `stop()` now joins the previous thread
(0.2 s timeout — worst case is one TICK_S = 33 ms) so the new
engine never races the old one.

### Fixed — `effectQuality` leaked `RENDER_INTERVAL_MS`

Picking Quality bumped the frame cap to 60 Hz as intended, but
switching back to Performance / Balanced left the cap pinned at
16 ms — the user's `frameRate` pick was forgotten until they
touched the dropdown again. Fixed by tracking the user's
frameRate-derived interval in `_userFrameInterval` separately.
The `effectQuality` case picks between that shadow value (for
performance / balanced) and the 60 Hz override (for quality).
`frameRate` writes update both globals, so dialling frameRate
while in Quality stages the new value for when the user later
drops out of Quality.

### Fixed — `SetCustomMode` left the engine in the wrong mode

OpenRGB GUI's "Custom mode" button fires `SetCustomMode` (packet
1100), which is semantically *"switch to the mode that accepts
UpdateLEDs writes verbatim"* — on our descriptor that's mode 0
(Direct). v1.6.3-beta routed it through the `UpdateMode` parser,
which bailed on the smaller payload but left `dev.mode_index`
pointing at the previous mode. Now `SetCustomMode` has its own
branch that flips `dev.mode_index = 0` and logs the transition.

### Added — `effectQuality` travels with presets

Added to `PRESET_SNAPSHOT_KEYS` so per-preset quality intent
("Cinema = Quality, Idle = Performance") survives Save/Apply.
`frameRate` / `glassQuality` / `gridRenderer` stay excluded.

### Changed — `math` hoisted to module-level import

`_effect_loop` had an inline `import math` and threaded the
module reference through `_render_mode(dev, now, math_mod)`. The
import is at the module top now, the parameter is gone, and the
render code references `math.sin` / `math.pi` directly.

### Changed — WALLPAPER_VERSION bump to 1.6.4-beta

`wallpaper/index.html` gained the `_userFrameInterval` shadow +
the corrected `effectQuality` / `frameRate` interplay + the
`#section-tabs` top offset bump. Lively / Wallpaper Engine
re-import required.

## [1.6.3-beta] - 2026-06-03

The **quality bucket + OpenRGB 2D** beta. Two follow-ups to v1.6.2's
SDK server work plus a long-requested perf/quality knob.

### Added — `effectQuality` per-screen setting

The v1.6.1-beta GPU sweep dropped the ambient / pixelfx / audio-glow
canvases to 0.5× backing resolution + DPR 1 to reach 0 % idle on a
5120×1440 surface. That's the right floor when nothing's happening,
but users on heavier hardware want the option to crank quality back
up. New per-screen `effectQuality` setting with three buckets:

| Bucket | Ambient backing | DPR | Frame cap |
|---|---|---|---|
| **Performance** *(default)* | 0.5× | 1.0 | per `frameRate` |
| **Balanced** | 0.75× | 1.0 | per `frameRate` |
| **Quality** | 1.0× | up to 2 | 60 Hz override |

Picker lives in the Effects tab next to ambient density. Default is
`performance` so the v1.6.1-beta GPU gains don't regress on
upgrade. Quality bucket roughly matches pre-v1.6.1-beta visual
fidelity at **~8–12× the GPU cost** of performance on 5120×1440
(16× pixel work from 0.5× → 1.0× backing buffer + DPR 1 → 2,
plus 2× from the 60 Hz override, partially absorbed by compositing
overhead).

Affects `#ambient-canvas` (snow / rain / sparks / constellation /
wormhole / …), `#pixelfx-canvas` (trail / glow / click ripple),
and `#audioglow-canvas` (pulse / spectrum / wave). A synthetic
window-resize event fires on bucket change so all three canvases
re-size on the next tick without a wallpaper reload.

### Fixed — OpenRGB SDK Static mode produced black output

Static doesn't carry the `HAS_BRIGHTNESS` flag, so the OpenRGB GUI
hides the brightness slider and sends a meaningless value
(typically 0) in the UpdateMode packet's brightness field. The
engine multiplied the picked colour by `0/100` → black wallpaper.

Fixed by ignoring the packet's brightness field on any mode that
doesn't advertise the flag. Static now renders the picked colour
at full brightness as intended.

### Changed — OpenRGB SDK zone back to MATRIX

v1.6.2-beta hotfix2 fell back to a `LINEAR` zone while we
suspected the matrix descriptor was the cause of the empty-Zone
dropdown. Hotfix3 showed the actual culprit was the bogus
`color_mode = 4` / `flags = 0x01` combo in the mode block. With
those corrected, switching back to `ZONE_TYPE_MATRIX` (matrix_size
= 8 + 4·W·H, row-major LED index map) is safe and gives effects
a proper 2D layout to walk.

Rainbow Wave + Color Wave now render 2D-aware: hue varies per LED
**column** instead of per linear index, then the column values get
replicated across rows. On a 32×16 wallpaper this is a real
horizontal sweep instead of left-to-right across a flat 512-LED
index range. Cost is O(W) HSV conversions per frame instead of
O(W·H) thanks to the row-replication trick.

### Changed — WALLPAPER_VERSION bump to 1.6.3-beta

`wallpaper/index.html` gained the `effectQuality` settings handler
+ helper functions + the three canvas resize functions migrated
from hard-coded scale/DPR to the quality-bucket helpers. Lively /
Wallpaper Engine re-import required.

## [1.6.2-beta] - 2026-06-02

The **wallpaper-as-virtual-device** beta. Inverts the v1.4/v1.5
OpenRGB direction: instead of the bridge consuming colours from real
OpenRGB devices, the bridge now exposes itself to the OpenRGB GUI as
a set of virtual matrix devices. Any built-in OpenRGB effect
(Rainbow Wave, Audio Visualizer, Breathing, …) can drive the
wallpaper backlight directly, without SignalRGB in the loop.

### Added — OpenRGB SDK server

New module `openrgb_server.py` speaks the OpenRGB SDK protocol on
the server side — the inverse of the v1.4 `openrgb_client.py` we
ship for the OpenRGB output channel. Architecture:

```text
+-----------------+        TCP/6743          +--------------------+
| OpenRGB GUI     | <----------------------> | Bridge SDK server  |
| (effect engine) |   ORGB protocol packets  | (openrgb_server.py)|
+-----------------+                          +--------------------+
                                                       |
                                            UpdateLEDs colours
                                                       v
                                              +--------------------+
                                              | wallpaper feed     |
                                              +--------------------+
```

One virtual device per screen. Each carries a single zone with a
`matrix_map` shaped to the screen's configured grid resolution
(default 32×16) so OpenRGB's effects that walk matrices produce
spatially-coherent output instead of treating the LEDs as a flat
strip. Device descriptor matches the byte layout the bridge's
existing client-side parser already handles — same module on both
ends of the protocol.

Default port is **6743** (not OpenRGB's standard 6742) to sidestep
the inevitable conflict on machines where both run. Listen address
is configurable; defaults to `0.0.0.0` so the OpenRGB GUI on the
same machine can connect via either `127.0.0.1` or the host's LAN
IP.

Thread-per-client model — multiple GUI instances can connect
simultaneously, last-write-wins semantics on the wallpaper.

### Added — `openrgb-sdk` as a per-screen source type

The per-screen source picker grows a fourth option alongside
SignalRGB / OpenRGB / sACN. Picking it routes that screen's
wallpaper feed to whatever the SDK-server clients are pushing. The
existing `SourceManager` gating ensures only frames from the
selected source make it to the wallpaper page — flipping a screen
between sources doesn't need any explicit re-routing in the SDK
manager.

### Added — Configurator OpenRGB SDK card

New sub-section in the Integrations tab below the existing OpenRGB
output block. Enabled toggle + port input + live status pill +
per-device summary (`Wallpaper Screen 1: 512 LEDs`). Status poll
against `GET /openrgb-sdk/status` every 2 s while the tab is
visible, surfacing running state + connected client count + bind
errors. i18n strings ship in EN + DE.

### Added — Built-in effect modes + bridge-side engine

Each virtual device ships 6 modes the OpenRGB GUI's Mode dropdown
exposes. Five mirror what real OpenRGB devices typically advertise;
**Color Wave** is bridge-specific.

- **Direct** — accepts `UpdateLEDs` writes verbatim (Effects
  Plugin / scripts)
- **Static** — solid colour from the picker
- **Breathing** — solid colour pulsing on `sin(t)` brightness
- **Rainbow** — uniform hue cycle across all LEDs
- **Rainbow Wave** — hue varies per LED position + time
- **Color Wave** — wave centred on the picked colour's hue (±15° range)

When the user picks a non-Direct mode in the GUI, the bridge-side
effect engine starts a 30 Hz daemon thread that renders the
corresponding pattern at the chosen speed / brightness / colour and
pushes the result through the same `_on_update_leds` callback
Direct uses. Speed slider 0..100 maps to per-mode cadence (Rainbow
cycles every ~5 s at 100, frozen at 0). Direct is skipped so the
GUI's writes aren't fought.

Full guide at [docs/openrgb-sdk-server.md](docs/openrgb-sdk-server.md).

### Fixed — descriptor format vs OpenRGB GUI

The descriptor went through five hotfix iterations against the
real OpenRGB GUI before connect → enumerate → mode-pick worked
end to end. Future SDK-server work should respect these:

- **Required `Direct` mode** — `num_modes = 0` segfaulted the GUI;
  every device needs at least one mode the selector + effect
  plugin can dereference.
- **Correct flag + `color_mode` enum values** — the first attempt
  used `flags = 0x01` thinking it meant `HAS_PER_LED_COLOR` (it's
  `HAS_SPEED`) and `color_mode = 4` which doesn't exist (valid
  range is 0..3). Wrong values → empty Zone dropdown, no LEDs
  parsed. Correct combo for Direct is `flags = 0x20`
  (`HAS_PER_LED_COLOR`) + `color_mode = 1` (`MODE_COLORS_PER_LED`).
- **Linear zone with `matrix_size = 0`** instead of a matrix
  descriptor — the byte encoding of `matrix_size` differs between
  OpenRGB server implementations and the right value for the GUI
  is still being pinned down. Linear zone works in the meantime;
  Rainbow Wave on a 32×16 device sweeps left-to-right across the
  full 512-LED index range instead of walking 16 rows of 32.
- **Pre-seeded mode-specific colours** — Static / Breathing /
  Color Wave advertised `colors_min = 1` but emitted
  `num_colors = 0`. The GUI's mode picker reads `mode.colors[0]`
  for the swatch preview unconditionally → buffer underflow →
  crash on click. Default-seeded with white per slot; the user's
  actual pick arrives via `UpdateMode` and the engine takes over.
- **Only expose active screens** — initial build iterated
  `N_SCREENS` (max slot count) instead of `config.screenCount`,
  showing 4 ghost devices for single-screen setups. `screenCount`
  changes now also kick `openrgb_sdk.reload()` so the GUI sees the
  new device list on next reconnect.
- **`_SETTABLE_BRIDGE_KEYS` whitelist entry** — without it, every
  `bridge-setting-update` for `openrgbSdkServer` got silently
  dropped before the elif handler ran; the Enabled toggle in the
  Configurator did nothing.

### Changed — APP_VERSION bump to 1.6.2-beta

WALLPAPER_VERSION stays at 1.6.1-beta — the SDK server runs entirely
in the bridge process and the new colour source flows through the
same wire format the wallpaper page already renders, so no
wallpaper/ side changes are needed in this release. Lively / WE
re-import is optional.

## [1.6.1-beta] - 2026-06-02

The **iteration + perf sweep** beta. v1.6.0-beta shipped Themes and
Mouse Distortion Effects; v1.6.1-beta tunes both, adds a new
cursor-aware ambient preset, restructures the Configurator IA, and
closes a fleet of GPU regressions that snuck in during the v1.6
work.

### Added — Wormhole ambient preset

Cursor-aware accretion-disc particle system. Particles spawn at
random screen positions outside the cursor's pull radius, accelerate
toward the cursor on an inverse-square gravity curve (`1.5e6 / dist²
+ 600`), and get consumed at the centre. Hybrid swirl tangent gives
the spiral feel. Density scales with screen area; consumption radius
+ outer escape + hard 3 s lifespan together keep the cluster from
piling up when the cursor sits still.

Position fed by both `window.livelyCurrentCursorPos` (click-through
on) and the canonical `document.mousemove` listener — works in any
Lively interaction mode.

### Added — 3 new widget themes

- **Gruvbox** — warm retro palette (orange / yellow on `#282828`)
- **Rose Pine** — soft purple-pink on a desaturated dark base
- **Cyberpunk Neon** — magenta + cyan accents on near-black

Brings the total to 11 themes. Picker switched from a `<select>` to
a swatch grid so themes are pickable by eye instead of by name.

### Added — Library category system

Every library entry now carries a `category` field — `background`
(default for image / video uploads), `template` (default for Builder
saves), or `both` (legacy / explicit). Auto-cycle's pool selector
gains a `Backgrounds only` option that excludes Builder source
images from the rotation. Library strip gains filter chips
(All / Background / Template / Pinned) with localStorage
persistence + a per-tile category badge. Right-click → category
picker re-categorises any entry.

Builder's Save → library defaults to `template`; the Configurator's
Upload button + drag-drop-as-background path both default to
`background`. Rename + duplicate preserve the source entry's
category.

### Added — Configurator R2: horizontal section tabs

The 9 settings cards used to live in one long scroll with a
left-rail nav (v1.2.1). Effects and System had grown into
mega-cards holding 5-6 sub-sections each. R2 splits the cards
across 5 tabs:

- **Look** — Background + Glow + Quick Looks
- **Effects** — Ambient + Mouse + Audio + pixelfx + parallax
- **Widgets** — Widget catalogue + Theme + tile style
- **Integrations** — OpenRGB / Sources / sACN / MQTT / REST / Plugins
- **System** — Presets + Per-app profiles + Backup + Screens

Sticky tab row below the screen picker; last-active tab
persisted; URL `#tab=KEY` deep-links. Tour steps gain a `tab`
field so the runner activates the right tab before measuring.

### Added — Preset thumbnails + audit

`PRESET_SNAPSHOT_KEYS` audit caught two settings that v1.6 had
silently dropped from Save / Apply: `widgetTheme` and
`mouseEffects`. The `cycle` dict is now snapshot at the
user-config sub-key level only (`enabled` / `intervalMin` / `pool`
/ `order`) — runtime state (`lastApplyMs` / `nextIdx`) stays live
across Apply.

Each filled slot button now renders an 80 × 45 client-side
thumbnail composed of the live background + dim overlay + widget
rectangles. Stored as a data-URL in the snapshot's `_thumb`
field. Older snapshots without `_thumb` fall back to the
empty-state look — no migration needed.

### Added — Library layout polish

Filter chips moved out of the `#library-strip` flex container into
their own row above (they were sharing wrap space with tiles).
Strip itself flipped from flex-wrap to CSS Grid with
`auto-fill, minmax(118px, 1fr)`; tiles drop their fixed 96 × 54
pixel size and ride the grid track via `aspect-ratio: 16 / 10`.
The "Add image…" button moved into the grid as a dashed
`.lib-tile-add` so it lines up with real tiles instead of
orphaning below.

### Fixed — Tab-init race (Effects ↔ Widget layout)

After Ctrl+F5 the user saw either the ambient-effect tile
previews stay empty OR the widget Layout-Vorschau render every
preview-widget at 0 × 0 px, depending on which tab restored from
localStorage. Same root cause in both spots — code reads element
dimensions during init while the tab is `display: none` →
`clientWidth` is 0 → layout permanently stuck on that 0.

`startTilePreview` now gets a `ResizeObserver` per tile canvas,
and `activateSectionTab` triggers a `renderLayoutPreview()` +
synthetic `window-resize` event when its tab becomes visible.
Together turns the XOR into "both work whichever tab you came
in on."

### Fixed — Theme always-visible feedback + cursor-fx rename

Theme picker showed no immediate confirmation that a change
landed. Added a 0.9 s pulse + box-shadow animation on every
widget when the theme switches (via `@property --pulse-scale`
registered so keyframes can interpolate without overwriting the
composed widget transform). "Cursor effects" renamed to "Mouse
effects" in i18n for consistency with the v1.6 marketing copy.

### Fixed — Widget composed transform

A previous keyframe-based `transform: scale(1)` rule on theme
change was overwriting the inline `transform: translate(x, y)`
that the widget position pipeline writes — every widget snapped
to the top-left corner for the duration of the pulse. Switched
to a CSS-variable composed transform: `--widget-x` / `--widget-y`
for position, `--repel-x` / `--repel-y` for repulsion, and
`--pulse-scale` (registered via `@property`) for the theme pulse.
The single `.widget { transform: translate(…) scale(…) }` rule
composes them so no keyframe can clobber position again.

### Fixed — Vintage CRT widget displacement

`body.theme-vintage-crt .widget { position: relative }` was
overriding the absolute positioning of widgets, dragging every
widget to the top-left. Removed `position: relative`, kept only
the `overflow: hidden` rule the CRT scanline pseudo-element
actually needs.

### Fixed — Mouse-effect z-index

Chromatic (z-index 1.5) and Spotlight (z-index 2.5) overlays sat
below `#bg` (z-index 2) so neither effect was visible. Raised
both to z-index 4 so they sit over `#bg` + `#dim` but below
widgets (z-index 5+).

### Fixed — `widgetTheme` + `mouseEffects` whitelist

`_SETTABLE_SCREEN_KEYS` was missing both keys so the bridge
silently rejected every theme switch + every mouse-effect
toggle. Added to the whitelist; both now round-trip correctly.

### Performance — uncapped rAF + DPR sweep

Audit triggered by a user report of ~19 % sustained GPU under
Snow on 5120 × 1440. Root cause was a bouquet of effect rAF
chains running uncapped at native 60 Hz + DPR ×2 backing buffers
on full-viewport canvases.

Fixed every effect rAF to gate on the global `RENDER_INTERVAL_MS`
cap (default 30 Hz):

- Ambient (all 17 presets — snow / rain / sparks / aurora /
  constellation / fireflies / plasma / vortex / bubbles / matrix
  / starfield / lightning / waves / ripples / flowfield /
  wormhole)
- Audio glow (pulse / spectrum / wave)
- pixelfx (trail / glow / click ripple)
- Mouse-fx repulsion / chromatic / spotlight / ripple — the last
  one was the worst single offender because `tick()` did
  `mapCanvas.toDataURL()` every frame
- parallax3d

Dropped DPR ×2 → ×1 on `#ambient-canvas`, `#pixelfx-canvas`,
`#audioglow-canvas`. Particle / gradient content is soft enough
that the upscale was invisible; on a 5120 × 1440 surface the
clear+fill cost per frame drops from 29.5 M pixels to 7.4 M.

Half-resolution backing buffer on `#ambient-canvas` (0.5 ×
viewport, CSS `width / height: 100%` for the bilinear upscale on
the GPU). `setTransform(0.5, …)` keeps the per-preset spawn /
step / render code in CSS pixel coords. Brought Snow from ~7 %
→ ~2 % on 5120 × 1440 after the cap + DPR fixes were in place.

Removed `will-change: transform` from `body.fx-repulsion .widget`.
It forced a GPU compositor layer per widget the entire time
Widget Repulsion was enabled, paid even when the cursor was
across the screen. Modern browsers auto-promote during the
transition itself; the always-on hint cost us nothing during
real repulsion but saved N × layer cost at idle. Same class as
the v1.4 [[gotcha-perf-transitions]] regression.

End state on 5120 × 1440: Snow + 3 widgets + glow settled at
~5-7 % GPU vs ~19 % before. Idle with nothing active = 0 %.

### Changed — WALLPAPER_VERSION bump to 1.6.1-beta

`wallpaper/index.html` saw widespread rAF + DPR + half-res
backing-buffer changes plus the new Wormhole ambient preset, the
3 new themes, the composed-transform pipeline, and the
mouse-effect z-index fixes. Workshop re-upload + Lively
re-import follow the same path as the v1.6.0-beta bump.

## [1.6.0-beta] - 2026-05-31

The **visual polish** beta. v1.5 closed the integration roadmap;
v1.6 turns to the look-and-feel surface that's been on hold since
the v1.1 widget tile-shell pass. Two stackable feature lines:

### Added — Widget Theme System

A new `widgetTheme` per-screen setting picks one of 8 coordinated
colour-palette + typography pairings that recolour every widget at
once. Independent of the v1.1 *Tile style* (Glass / Solid /
Clear / Off) — tile style = shell chrome, theme = palette
underneath. CSS-variable based: each theme is one `body.theme-<n>`
class that sets `--theme-bg-glass`, `--theme-bg-solid`,
`--theme-bg-clear`, `--theme-border`, `--theme-fg`,
`--theme-fg-muted`, `--theme-accent`, `--theme-font`.

Built-in themes:

- **Default** — the v1.5 glow-tinted palette (visual no-op for
  existing users who don't pick a theme)
- **Dracula** — purple accent on `#282a36`
- **Nord** — cool blue-grey, the Arctic palette
- **Tokyo Night** — very dark blue + cyan accent
- **Catppuccin Mocha** — warm dark mode + pink accent
- **Solarized Dark** — the developer-classic high-contrast palette
- **Vintage CRT** — monospace green on near-black with a soft
  text-shadow glow; pairs with the audio-spectrum + matrix
  ambient for an actual CRT-monitor vibe
- **Light Mode** — daylight palette for users editing in bright
  rooms

### Added — Mouse-driven distortion effects

Four stackable mouse-position-driven effects, configured via a
multi-checkbox in the per-screen Widgets card. All four can run
concurrently; each one is independent. Disabled inside the
Configurator's `?preview=1` iframe so the preview stays cheap.

- **Widget Repulsion** — widgets ease away from the cursor via a
  smoothed rAF loop that writes `--repel-x` / `--repel-y` CSS
  variables. 220 px radius, 50 px max push, cubic-bezier ease.
  No compositor cost beyond the existing widget layers.
- **Chromatic Aberration** — three R/G/B radial gradients at
  offset positions around the cursor, `mix-blend-mode: screen`
  recombines them. Falls off to invisible past ~250 px. Adds
  one overlay div, no per-frame canvas work.
- **Magnify Spotlight** — radial-gradient mask following the
  cursor: transparent disc inside 100 px, fading to 55 % black
  past 240 px. Reading-lamp-in-a-dark-room effect.
- **Liquid Ripple** — SVG `<feDisplacementMap>` on the
  background + glow grid. A small 256 × 256 canvas renders the
  decaying displacement map (encoding cursor movement as
  R + G offsets); the feImage references the canvas via a
  per-frame dataURL refresh. Most expensive of the four —
  opt-in only.

### Changed — WALLPAPER_VERSION bump to 1.6.0-beta

`wallpaper/index.html` gained the theme CSS variable system + the
MouseFx module + the `applyMouseEffects` / `applyWidgetTheme`
property handlers. Workshop re-upload + Lively re-import follow
the same path as the v1.5 bump.

## [1.5.0-beta] - 2026-05-30

The **LED ecosystem hub** beta. v1.4.0-beta opened a single one-way
channel from the bridge to OpenRGB; v1.5.0-beta turns the bridge into
a small switchboard: pick *per screen* whether the wallpaper takes
its colour from SignalRGB, an OpenRGB device, or an incoming sACN
universe, and stream the resulting glow back out to both OpenRGB and
sACN simultaneously. The OpenRGB output also moved from "one
averaged colour per screen" to per-device spatial sampling —
each device follows the colour at *its* position on the wallpaper,
configured via a draggable live preview.

### Added — sources

- **Per-screen colour-source picker** in *System → Settings*. Each
  screen can independently take its glow colour from:
  - **SignalRGB** (existing UDP plugin path — default, no behaviour
    change for current installs)
  - **OpenRGB** — bridge polls a chosen device's current LED colours
    via the OpenRGB SDK at 30 Hz and averages them into the
    wallpaper glow. Useful when SignalRGB isn't running but
    OpenRGB-native effects are. Caveat documented in the
    Configurator: hardware-effect modes (firmware-driven Rainbow
    Wave etc.) don't expose the live frame over the SDK; OpenRGB
    must be in Direct mode with some software effect engine pushing
    frames the bridge can then read.
  - **sACN / E1.31** — bridge subscribes to a chosen multicast
    universe on port 5568 and uses the first three DMX channels
    (R, G, B) as the source colour. Lets xLights, QLC+, Hyperion,
    Razer-Chroma adapters or any sACN sender drive the wallpaper.
- **`SourceManager`** internal routing layer. Validates every
  incoming frame against the per-screen source config so a still-
  running SignalRGB plugin can't fight a screen the user just
  switched onto OpenRGB.

### Added — outputs

- **sACN / E1.31 output emitter** — parallel to the v1.4 OpenRGB
  output channel. Hooks the broadcaster's frame-tap; emits one
  universe per screen at 30 Hz with configurable priority,
  multicast destination (standard E1.31, default) or unicast
  destination (specific receiver IP).
- **Spatial mapping for the OpenRGB output channel** — each
  enumerated device has a normalised `(x, y)` position; the
  bridge samples the live wallpaper grid at that point instead of
  averaging the whole screen. Configurator's *System → OpenRGB
  output* sub-section grew a 480×270 live-preview canvas with a
  draggable marker per device — marker fill reflects the live
  sampled colour, drag commits the new position via WS. The
  preview WS is opened only while the System card is visible AND
  the output is enabled AND devices have been enumerated, so it
  costs nothing off-screen.
- Both outputs run from the same averaged colour stream, so a single
  effect drives wallpaper + OpenRGB hardware + DMX lighting in
  perfect sync.

### Added — internals

- **`sacn_codec.py`** — minimal ANSI E1.31 packet pack/parse,
  stdlib-only. Shared by the input + output managers; round-trip
  tested.
- **`openrgb_client.get_colors()`** — read the current LED array
  from an OpenRGB controller (companion to the v1.4 `push_color`).
  Implemented via `REQUEST_CONTROLLER_DATA` with a forward-walking
  parser past the LED descriptors.
- **HTTP status endpoints** `/sacn/status`, `/sacn-input/status`,
  `/openrgb-input/status`, `/sources/status` for the Configurator's
  live state pills. `/openrgb/status` now also includes
  `bridgeVersion`, `protocolUsed` and `parseErrors[]` so a forgotten
  installer step (stale exe) or a stuck enumerate is obvious from
  the UI without needing console logs.
- **`WALLPAPER_VERSION` constant**, independent of `APP_VERSION`.
  The wallpaper-bundle "out of date" handshake compares against
  this, not the bridge version. Bridge-only releases (v1.4 OpenRGB
  output, v1.5 sources / sACN — neither touched `wallpaper/`)
  therefore no longer raise the banner on every install with
  bundles still stamped at the last wallpaper-touching release
  (1.3.0 today). `installer/build.ps1` reads the constant from
  `bridge.py` and stamps the Lively / WE bundles with it.

### Fixed

- **`_get_bridge_state`** now echoes the nested config blocks
  (`openrgbOutput`, `sources`, `sacnOutput`) so the Configurator's
  System sub-sections actually reflect persisted values across tab
  refreshes. Regression from v1.4.0-beta where the OpenRGB
  host/port/source-screen fields appeared at their defaults even
  after the user saved a custom config.

#### OpenRGB SDK parser — five hotfix iterations on real hardware

Validated against OpenRGB 1.0rc2 + an ASUS ROG STRIX GeForce RTX
4070 Ti + the bundled E1.31 plugin. Every iteration was caught by
the diagnostic-log surface added in the second pass:

- **Mode-struct size** 44 → 48 bytes for protocol 3+. I had 11
  uint32s where proto 3+ actually carries 12 — the `brightness`
  field was missing. Every device's mode block fell out of
  alignment, num_zones overflowed past end-of-buffer, parser
  raised, enumerate returned an empty list.
- **Protocol negotiation**: the spec says the client must take
  `min(client_claim, server_reply)` after the handshake. My
  client was blindly using the server's reply, so against a
  proto-5 server it tried to parse proto-5-format data with our
  proto-4 walker.
- **String wire format**: `controller_data` uses uint16-LE
  length-prefixed strings, not null-terminated. My parser used
  null-termination logic which works for SET_CLIENT_NAME but
  desynced everything inside controller_data.
- **Vendor string** field added in proto 1+ — slot between
  `name` and `description`. Skipping it shifted every subsequent
  field by one, eventually landing the length-prefix read
  mid-mode-block on bytes that parsed as gigantic bogus string
  lengths (~14-20k).
- **Socket-broken vs no-LEDs split** on both `push_color`
  (output) and `get_colors` (input). Previously both paths
  returned False on either condition, so a 0-LED device (E1.31
  plugin, virtual SDK controllers) made the manager loop endlessly
  in connect → enumerate → push → "treat False as failure" →
  disconnect → backoff → repeat.
- **Configurator JS scope bug** that hid the spatial-mapping
  editor: `s` (the `/openrgb/status` response) was declared
  `const` inside a `try` block; the visibility-flip code outside
  the block referenced it, raising `ReferenceError` that the
  defensive catch-all swallowed silently, so the editor never
  unhid even when conditions held.

### Added — strip mode for OpenRGB output

Multi-LED devices (RAM, light strips, keyboard rows, fan rings) can
follow a *line* on the wallpaper instead of a single point. Each
LED on the device samples its position along the line, so a
horizontal stick of RAM shows a horizontal gradient that tracks
the wallpaper underneath. Toggle per-device from a Point ● / Line ↔
button under the live-preview canvas; line mode adds a second
draggable endpoint with a yellow ring + a gradient stroke between
the two endpoints. Backward-compatible: any device without a `mode`
field collapses to point mode (= v1.4-style single sample).

### Added — REST API + token auth + OpenAPI spec

The bridge already exposed a handful of HTTP endpoints
(`/config`, `/library/list`, `/hwmon/sensors`, …). v1.5.0-beta
formalises the surface under `/api/v1/*`:

- `GET  /api/v1/info`                          bridge version + capabilities
- `POST /api/v1/auth/verify`                   verify the supplied token
- `GET  /api/v1/screens`                       list screens with summary
- `GET  /api/v1/screens/<n>/settings`          per-screen settings
- `POST /api/v1/screens/<n>/preset/<slot>/apply`   apply a preset
- `POST /api/v1/screens/<n>/pause`             {paused: bool}
- `GET  /api/v1/profiles`                      per-app rules
- `GET  /api/v1/plugins`                       installed widget plugins
- `GET  /api/v1/sacn/discovered`               passively-discovered sACN senders
- `GET  /api/v1/mqtt/status`                   MQTT bridge state
- `GET  /api/openapi.json`                     hand-written OpenAPI 3.1 spec

Auth: loopback requests bypass (Configurator + same-host
integrations need zero config); remote requests need
`Authorization: Bearer <apiToken>`. Token auto-generated on first
run, shown + regenerable from the Configurator's System card.

### Added — sACN/E1.31 universe discovery

The sACN input manager additionally joins the
`239.255.250.214` multicast group to passively catalogue every
E1.31 sender on the LAN (xLights, sACN View, OLA, Hyperion,
custom controllers, …). Senders re-announce every ~10 s; we
track `{cid: {sourceName, universes[], lastSeen}}` and prune
entries that go silent for >35 s. Surfaced via
`/api/v1/sacn/discovered` so the Configurator can offer a pick-
list instead of "type the universe number".

### Added — generic HTTP widget

New widget type `http` covers Discord-unread / stock-ticker /
RSS-headline / crypto-price / arbitrary REST API in ONE widget
instead of one widget per service. Fetches a user-configured URL
on a refresh interval, parses JSON (or treats as text), runs the
result through a tiny mustache-flavoured template
(`{{path.to.field}}` substitutions). Lives on the wallpaper page;
no bridge proxy — the target's CORS + cache headers apply.

### Added — Home Assistant / MQTT bridge

The bridge publishes per-screen state and subscribes to control
topics under a configurable prefix (default `signalrgb-wallpaper`):

- `<prefix>/bridge/online`              "online" / "offline" (LWT, retained)
- `<prefix>/bridge/version`             bridge version (retained)
- `<prefix>/screen/<n>/preset`          active preset slot (retained)
- `<prefix>/screen/<n>/preset/set`      subscribe — apply preset slot
- `<prefix>/screen/<n>/pause`           "on" / "off" (retained)
- `<prefix>/screen/<n>/pause/set`       subscribe — pause / resume
- `<prefix>/screen/<n>/background`      current background path
- `<prefix>/screen/<n>/glow`            "#rrggbb" from the live frame tap

Custom 400 LOC MQTT 3.1.1 client (`mqtt_client.py`) — stdlib only,
no paho-mqtt dependency. Disabled by default; password redacted to
"***" in the WS bridge-state push so a Configurator screenshot
can't leak broker credentials, restored from the on-disk config
when the Configurator pushes back unchanged.

### Added — Plugin API for 3rd-party widgets

The bridge scans
`%LOCALAPPDATA%\SignalRGBWallpaper\plugins\<name>\` on startup
and on demand for `manifest.json` files. Each discovered plugin
becomes a `plugin/<name>` widget type. Each instance renders
into a sandboxed iframe (`sandbox="allow-scripts"`, no
same-origin / no top-nav / no forms) served from
`/plugins/<name>/<asset>`. The HTTP route refuses path
traversal; assets ship with a strict `Content-Security-Policy`
header.

Wallpaper page ↔ plugin contract uses `postMessage` only:

- `{type: "init",  options, tint}` once on iframe load
- `{type: "tint",  color}` on every glow-colour change + 1 Hz
- `{type: "opts",  options}` on options edit

Full author contract documented in [docs/plugin-api.md](docs/plugin-api.md).
Minimal hello-world example included in the doc.

### Changed — WALLPAPER_VERSION bump to 1.5.0-beta

`wallpaper/index.html` gained the generic HTTP widget runtime
plus the plugin iframe + postMessage dispatcher, so the
wallpaper-bundle version constant moves from `1.3.0` to
`1.5.0-beta`. Existing 1.3.0 / 1.4.0 bundles will trigger the
"out of date" banner on first connect. **Shipping this beta will
require a Workshop re-upload + Lively re-import** — handled by the
installer's auto-import task; Workshop submitters run
`installer\maintainer-restore-workshopid.ps1` first per the v1.4
gotcha.

### Notes

Default behaviour for an upgrading user is still mostly unchanged:
every screen starts on `signalrgb`, OpenRGB output stays off, sACN
output stays off, every device's spatial mapping defaults to
(0.5, 0.5) which matches v1.4's averaged behaviour on uniform
effects, MQTT bridge stays off, no plugins shipped by default,
REST API token is generated but external clients can't reach the
bridge yet (loopback-only binding). The new channels light up only
when the user opens the System card and enables them.

## [1.4.0-beta] - 2026-05-30

First beta of the **LED ecosystem expansion** line. v1.3.0 stayed
self-contained (wallpaper page + per-screen SignalRGB device); v1.4.x
opens up a one-way output channel from the bridge to other lighting
ecosystems so the same glow colour that paints the wallpaper can also
drive the rest of the user's RGB hardware.

### Added

- **OpenRGB output channel** — opt-in network-SDK client that
  connects to a running OpenRGB instance (default
  `127.0.0.1:6742`) and mirrors a chosen source screen's averaged
  glow colour onto every enumerated OpenRGB device at 30 Hz.
  Pure-Python custom client (no openrgb-python dependency, so the
  bridge keeps its MIT licence). Configurator surfaces a new
  *OpenRGB output (beta)* row in **System → Settings** with
  enable / host / port / source-screen + a live status line that
  shows the connection state and device count. Disabled by
  default — users who don't run OpenRGB pay nothing.
- **Broadcaster frame-tap hook** — internal extension point that
  lets per-frame subscribers (OpenRGB output manager today,
  sACN/E1.31 emitter in a future beta) receive the same averaged
  colour the wallpaper page sees, without forking the broadcast
  path or paying the WS encoding cost twice.

### Notes

This beta touches the bridge + Configurator only — no changes to the
Lively, Wallpaper Engine or SignalRGB-plugin code paths. Existing
wallpaper installs continue to work unchanged; the OpenRGB row is
purely additive and stays dark unless the user opens the System card
and flips it on.

## [1.3.0] - 2026-05-29

Cuts the v1.2.7 – v1.2.13 beta line into a single stable release.
Headline themes: **performance**, **security**, **multi-monitor
workflow**, **video-friendly Library**.

### Performance

- **Matrix-ambient render pipeline rewrite** — font + colour-LUT
  hoist, integer-Y snap, `MATRIX_CHARS` interned-string array,
  particle pool + `respawn()` hook, `Array.splice` → swap-and-pop,
  batched `renderAll()` by colour bucket. Lively WebView2 CPU on a
  3-screen Matrix-dense stress run drops ~12 % → ~1.5 %.
- **`frameRate` setting** (Performance 20 Hz / Balanced 30 Hz /
  Quality 60 Hz). Both ends of the pipeline read the same value:
  `Broadcaster.broadcast_frame` caps the outgoing per-screen WS
  stream, the wallpaper page's `renderFrame` caps at the same.
  SignalRGB's plugin frequently sends UDP at 150–200 fps for cheap
  effects (Solid Color); at 30 Hz the blur layer is perceptually
  identical and the pipeline does half the work. The Configurator
  surfaces a live plugin send-rate readout next to the dropdown.
- **Grid renderer** is now per-screen settable: default DOM (cheaper
  on GPU via Chromium's solid-rectangle fast-path) or opt-in Canvas
  (one `putImageData` per frame; cheaper on CPU but shifts cost to
  the GPU on dGPU-rich setups).
- **Pause state fix** — the tray's *Pause glow + animations* used to
  leave ~10 % GPU because all four rAF loops (ambient / audio-glow /
  pixelfx / parallax) kept scheduling at 60 Hz. Now: a CSS-driven
  `body.paused-glow` class removes the five filter-heavy layers
  from the compositor entirely, AND each rAF cancels its chain on
  pause and rearms via a `wallpaper-resume` event.
- **Glass-tile backdrop-filter** reduced from `blur(12 px)` to
  `blur(6 px)` + `contain: paint` + `will-change: backdrop-filter`
  hints, plus a new `glassQuality` per-screen setting (low / medium
  / high) that lets users at either GPU extreme tune the cost.
- **Standby card** ("Bridge offline") no longer burns ~20 % GPU on
  its own — dropped the `backdrop-filter` on the card, replaced the
  `box-shadow` pulse animation with `transform: scale` on a pseudo.
- **`probeRafLoop` throttled** 60 Hz → ~5 Hz via setTimeout cascade.
  Page-pause detection still works (paused page never fires rAF at
  all); WebView2 compositor stops getting woken just for a timestamp.
- **UdpReceiver short-circuit** before any broadcaster work when
  paused or no client is listening on the target screen. Earlier
  betas in this line still created an `asyncio.Task` per UDP
  packet, churning CPython's heap unnecessarily.
- **Per-channel backpressure** on `push_sysstats` / `push_pause` /
  `push_reload_all` / `push_settings` (same 256 KiB cap
  `broadcast_frame` already used).
- **Widget-command thread pool** — the per-message `threading.Thread`
  spawn that handled `widget-update`, `setting-update`, etc.
  could easily fire thousands of threads during a Builder drag.
  Now submitted to the asyncio loop's default `ThreadPoolExecutor`.
- **SMTC manager cached** in `NowPlayingPoller`; idle-gate on all
  pollers (`SysStats` / `HwMon` / `NowPlaying`) — they only fire
  when a widget that actually consumes their data is placed on
  some screen.
- **Bridge-side broadcast cap** keyed off the same `frameRate`
  setting the page reads — closes the WS pipeline at the source
  instead of letting WebView2 decode 150 fps just to drop 130
  of them.
- **Page-side micro-fixes** — `ensureZones` early-returns in
  canvas-render mode, `_anyTintedWidget()` cached + invalidated
  on widget mutation, GC heartbeat every 60 s + diag log line
  every 5 min (`[diag] rss=… tasks=… clients=… partials=…`).

### Security + robustness

- **Tray-update path overhauled** — PyInstaller switched from
  `--onefile` to `--onedir` (no temp extraction, no temp-permission
  / AV race surface; ~2× faster startup), and the post-install
  bridge relaunch no longer leans on Inno's `[Run]` section. The
  old bridge spawns a detached `cmd.exe` child that waits 40 s
  via `timeout` (not `ping`, AV-friendlier) then `start "" /B`s
  the new exe as a normal user-context process. Together this
  closes the "Failed to load Python DLL python313.dll" error
  several users hit after the tray-triggered silent update.
- **CORS lockdown** — every HTTP response migrated from
  `Access-Control-Allow-Origin: *` to a per-origin whitelist
  (bridge loopback / `null` for file://-style WebView2 / any
  `*.localhost` subdomain so Lively + WE's WebView2 hosts both
  work). The WS handshake gets the same check.
- **`/library/<file>` path-traversal hardening** — URL-decode
  before the literal `/ \ ..` check, anchor the resolved path
  under `library_dir()` so a symlink can't escape either.
- **CI smoke test** workflow on push + PR (`py_compile` + import +
  module-level invariant spot-checks).
- **WS protocol versioning** + **config schema migration scaffold**
  — fields land on every settings push (`wsProtocolVersion`) and a
  `_migrate_config()` hook runs before the generic backfill so the
  next time a key shape changes there's a clean entry point.
- **Persistent rotating bridge log** at
  `%LOCALAPPDATA%\SignalRGBWallpaper\logs\bridge.log` (1 MiB ring,
  3 backups). `--noconsole` was previously dropping stdout/stderr
  to NUL — when a user reported a silent crash there was nothing
  to read. Diagnostics export now folds the log into the bundle.
- **Provider init validation** — `BridgeRuntime._serve` prints a
  loud `[init] WARNING` if `hwmon_provider` / `udp_provider`
  aren't wired before `serve_forever`.
- **Look bundles can't override hardware-perf prefs** —
  `quick_look_apply` filters `gridRenderer` / `glassQuality` /
  `frameRate` out of the incoming bundle settings.

### Multi-monitor + Builder workflow

- **Wallpaper-bundle / bridge version handshake** — `build.ps1`
  stamps the bridge version into the bundle's `index.html` meta
  tag; the page sends `{type:"hello", wallpaperVersion}` on WS
  connect; the bridge pushes a banner-driving
  `{type:"version-mismatch"}` back when the bundle's older than
  `APP_VERSION`. Dev-tree pages report `"dev"` and bypass the
  check.
- **Configurator UX sweep** — *Open library folder* button next to
  *Choose image…* pops Explorer at
  `%LOCALAPPDATA%\SignalRGBWallpaper\library`; orientation toggle
  in the monitor-setup popover no longer closes itself on click;
  section-nav rail keeps the explicit click highlight on short
  cards (Profiles + Backup) for 700 ms; header connection status
  no longer stuck on "verbinde…" for single-monitor setups.
- **Builder 4-step intro** refreshed (span / orientation moved to
  the Configurator's per-tab gear in v1.2.10, the Builder no
  longer hosts that step).
- **Builder span-split** — inline auto-detect on every image-load
  path. When the user picks an image and the image is ≥1.5×
  the target tile's pixel size AND the tile is part of a
  multi-tile span, the Builder asks: *spread across the whole
  span or keep it inside just this tile?* The split path crops
  the source proportionally to each sibling tile's region within
  the bridge-screen composite — drop a 5120×1440 panorama on one
  half of a 2×2560×1440 span and each monitor receives its half.
  Triggers on File picker / Library tile / drag-into-tile /
  *Use current canvas* / drag-into-editor (editor variant adds an
  *Open in editor* third option since there's no tile context).

### Video backgrounds

- **MP4 / WebM / MOV / M4V end-to-end fixes** continuing from
  v1.2.6 — `_update_background` magic-byte-sniffs the upload so
  videos save with the correct extension; `/image` proxy accepts
  video extensions and serves `Range` requests as `206 Partial
  Content` with 256 KiB chunked streaming.
- **Library tile + hover preview render real video frames** — tile
  embeds a `<video preload="metadata">` for entries without a
  separate poster companion (so older video uploads work too);
  the hover popup ships both `<img>` and `<video>` and picks one
  based on file extension. New `/library/thumb` endpoint + a
  client-side `extractVideoPoster()` extract a still frame on
  upload so fresh entries get a static `.thumb.png` companion.
- **`_clearVideoBg()` teardown overhauled** so switching from a
  video bg back to an image actually releases the WebView2
  decoded-frame pool (the user-reported "RAM stays full" case).

### HwMon

- Sensor picker dropdown now categorised — LHM tree path's host
  segment stripped, device + category joined as the `<optgroup>`
  label, sensor leaf as the option label. The select renderer
  learned opt-in `<optgroup>` support that other selects ignore.

### Note — MP4 transparency for "glow through video"

Several users have asked whether a video wallpaper can let the
SignalRGB glow show through transparent regions, the way a PNG
with alpha does. **MP4 (H.264) has no alpha channel** — glow zones
can only stack *on top of* an MP4, not show *through* it. For
animated wallpapers with glow showing through, the working formats
are **WebM with VP9-alpha**, **APNG**, or **animated AVIF**.

## [1.2.13-beta] - 2026-05-29

> Beta: Library tiles for video background uploads (MP4 / WebM /
> MOV / M4V) now render a still-frame poster instead of a blank
> box. CSS `background-image: url(*.mp4)` doesn't actually decode
> video in any browser, so the Configurator's Library row showed
> nothing for video items — even though the videos themselves
> worked perfectly as the live wallpaper background.

### Fixed — Library tile shows blank for MP4 / WebM / MOV uploads

When the Configurator's *Choose image…* picker uploaded a video,
`/library/upload` saved the file under its native extension (the
fix in v1.2.6 that magic-byte-sniffs the format), and
`_library_rebuild_catalogue` happily added an entry — but with
its `thumb` field falling back to the video filename itself.
`renderLibraryTile` then set `background-image: url(/library/foo.mp4)`,
which CSS can't render: there is no rule in CSS or HTML to use a
video file as a `background-image`. Tile stayed blank.

Two-part fix:

- **New `POST /library/thumb?name=<slug>` endpoint on the bridge**.
  Accepts a raw PNG (magic-byte verified) and saves it as
  `<slug>.thumb.png` in the library dir. Triggers
  `_library_rebuild_catalogue` so the entry's `thumb` field
  points at the new poster on the next `/library/list` poll.
  Slug input is sanitised against `_LIBRARY_SAFE_CHARS` (same
  whitelist `_library_slug` produces) so the endpoint can't be
  used for path traversal.
- **Configurator-side poster extraction**. A new
  `extractVideoPoster(file)` helper loads the video into an
  off-screen `<video>` (muted, `preload="metadata"`), waits for
  `loadedmetadata`, seeks to ~0.5 s (or 10 % of duration,
  whichever is shorter — black opening frames are a thing), then
  on `seeked` draws to a canvas downsampled to ≤480 px wide and
  `canvas.toBlob`s a PNG. The existing video-upload path in the
  `bg-file` change handler now follows the main `/library/upload`
  with a `/library/thumb` call carrying that poster. Best-effort:
  on any failure (codec the browser can't decode, timeout, etc.)
  the tile stays blank and the upload status line surfaces
  `(poster skipped)`.

The bridge serves the resulting `<slug>.thumb.png` through the
existing `/library/<file>` static route, so no Configurator-side
change to `renderLibraryTile` was needed — it already picks
`item.thumb || item.file`, which now resolves to the poster.

### Fixed — Library tile + hover-preview render real video frames

The v1.2.13 first pass added a `/library/thumb` endpoint and a
client-side `extractVideoPoster()` that uploads a still frame
alongside the video — but that only kicks in for *new* uploads.
Existing video entries with no companion `.thumb.png` still
rendered the tile + the hover-preview popup via CSS
`background-image` / an `<img>` tag, which can't decode video.
Result: blank tile, broken-image icon in the popup.

Tile + preview now branch on file extension:

- **Tile**: if the catalogue has a non-video `thumb` companion,
  the CSS-background path stays (cheapest). Otherwise the tile
  embeds a `<video preload="metadata" muted>` whose first frame
  the browser decodes as a static poster. No autoplay, no
  controls, `pointer-events: none` so the parent button keeps
  the click.
- **Hover preview popup**: now ships both `<img>` and `<video>`
  in the template; `showLibraryPreview()` picks one based on the
  file extension and clears the inactive element so a
  previously-opened video doesn't keep decoding in a hidden popup.

### Added — Span-mode apply dialog (still images only)

The Library Apply path used to silently overwrite the screen's
`bgImage` with the single library file, which for a screen
configured in `span-h` / `span-v` mode means a still image gets
stretched across the whole composite. Usually wrong.

`applyLibraryItem` now detects `monitorSetup.mode !== "single"`
**and** the item is a still image (not a video) and pops a small
modal:

- **Im Builder öffnen…** — opens `/builder?screen=N&library=<file>`
  in a new tab so the user can compose per tile via the Monitor
  Wall workflow. Highlighted as the recommended default.
- **Beide spannen** — keep the previous behaviour and stretch the
  image across the span.
- **Abbrechen** — close, do nothing.

Videos skip the dialog entirely and fall straight through to the
normal apply path: the Builder's per-tile workflow is image-only
(canvas-based crop/place), so there's nothing useful it could do
with an MP4, and span-stretching a video usually looks fine
because the motion masks distortion. Single-mode screens also
skip the dialog.

### Security — CORS + WS Origin lockdown

Pre-v1.2.13 every HTTP endpoint returned `Access-Control-Allow-Origin:
*` and `_serve_websocket` accepted any `Origin` on the WS handshake.
Bridge is bound to 127.0.0.1 so it isn't reachable from the network,
but any web page the user happened to load in their browser could
still `fetch("http://127.0.0.1:17320/library/upload?name=evil", …)`
or `new WebSocket("ws://127.0.0.1:17320/?screen=0")` in the
background and dispatch `setting-update` / `widget-add` /
`system-action` against the bridge. Real one-click-attack surface.

- New `_ALLOWED_HTTP_ORIGINS` whitelist (the bridge's loopback URL,
  the `localhost:17320` alias, and `null` for any file://-style
  WebView2 sandbox). `_acao()` helper resolves the right ACAO
  value per response; every `*` site got migrated.
- On top of the explicit list, the origin check also accepts any
  host whose hostname is `127.0.0.1`, `localhost`, or a
  `*.localhost` subdomain — both Lively and Wallpaper Engine
  serve their WebView2 wallpaper pages from a random-hex
  `<id>.localhost` HTTPS origin (e.g.
  `https://bbeebe4f83f8bc83.localhost`). RFC 6761 reserves
  `.localhost` for loopback so a remote site can't impersonate
  it.
- WS handshake rejects 403 when the request's `Origin` is set and
  not whitelisted. Tools without an Origin header (curl, native
  bridges) keep working — the check is opt-in to refusal.
- Path-traversal check on `GET /library/<file>` now URL-decodes
  before the `/ \ ..` check (the literal-only check missed `%2F`
  / `%5C` / `%2E%2E`) AND anchors the resolved path under the
  library dir via `Path.relative_to`, so a symlink under
  `library/` can't escape either.

### Added — CI smoke test (GitHub Actions)

No CI existed before this release — every regression got caught
by a maintainer or a user. New `.github/workflows/smoke.yml` runs
on push + PR:

- `python -m py_compile wallpaper_bridge/bridge.py` (syntax check)
- `import bridge` (catches module-level errors)
- Module-level invariant checks (the new `frameRate`,
  `gridRenderer`, `glassQuality` defaults exist, helpers like
  `parse_http_headers` and `_acao` are callable, `WS_HOST` is
  still loopback).

Adding more invariants is cheap once the workflow is in place.

### Added — WS protocol version + config schema migration scaffold

- `WS_PROTOCOL_VERSION = 2` constant. Settings push now carries
  `wsProtocolVersion` so a wallpaper page or Configurator tab
  loaded from an older bundle can detect a breaking change before
  dispatching a malformed message. Bumped any time an existing
  message type changes shape; new types alone don't need a bump.
- `_migrate_config(cfg)` is called before the generic setdefault
  backfill in `load_config`. Empty for now (additions so far have
  all been backfill-friendly), but the next time a key gets
  renamed or its inner shape changes the migration goes here +
  the existing `CONFIG_VERSION` bumps.

### Added — Persistent rotating bridge log + diagnostics inclusion

`--noconsole` PyInstaller sends stdout / stderr to NUL — when a
user reported "the bridge crashed silently" there was nothing to
read. `_setup_persistent_logging()` redirects both into a
`RotatingFileHandler` at
`%LOCALAPPDATA%\SignalRGBWallpaper\logs\bridge.log` (1 MiB ring,
3 backups, 4 MiB total disk cap). The tray's *Export diagnostics*
already fans the bundle into a Zip on the desktop; that bundle
now also includes `logs/bridge.log*` so a maintainer reading a
user-submitted report has the actual log lines.

### Added — Provider init validation

`BridgeRuntime._serve` now prints a loud `[init] WARNING` if the
broadcaster is missing `hwmon_provider` or `udp_provider` when
`serve_forever` starts. Pre-v1.2.13 a typo in startup wiring fell
through silently — picker endpoints just returned empty data.

### Fixed — Video bg → image bg leaves the video buffer allocated

A tester reported that switching back from an MP4 background to a
regular image kept the wallpaper page's RAM at "video size". Cause:
`_clearVideoBg()` did `pause()` + `removeAttribute("src")` +
`load()`, but Chromium / WebView2's HTMLMediaElement holds the
decoded-frame pool well past those calls (a documented quirk).
Aggressive teardown — `src = ""` then `load()`, plus removing the
`currentTime` attribute and resetting our own `dataset.currentSrc`
duplicate-load guard — actually releases the buffer in WebView2.

### Improved — HwMon sensor picker categorised by sensor tree

The picker that powers the *hardware-sensor* widget used to be a
flat `<select>` with every sensor LHM reports (often 100-300
items) thrown in. Useless on multi-device machines.

`_buildSensorOptions` now strips the LHM tree's host segment,
joins device + category into a group label
("AMD Ryzen 7 5800X / Temperatures"), and uses the sensor leaf as
the option label. The select renderer learned to honour an
optional `group` field on options → opt-in `<optgroup>` wrappers
without touching any other select field in the Configurator.
Sorted alphabetically so related sensors end up adjacent.

### Fixed — Configurator + Builder UX sweep

Six items from a session walkthrough, all small but each one a
real friction point:

- **Background card** loses the standalone *Image path* text input
  — almost nobody pastes a Windows path, and the *Choose image…*
  picker + Library tiles cover the rest. The text input stays in
  the DOM hidden so any JS / external automation that reads
  `#bg-image` keeps working, and a new **Open library folder**
  button next to *Choose image…* pops Explorer at
  `%LOCALAPPDATA%\SignalRGBWallpaper\library` via a new
  `open-library-folder` system-action handler — drop-many-files
  in one go instead of clicking *Choose image…* per file.
- **Monitor-setup popover orientation toggle** no longer closes
  itself when the user flips a tile between landscape and portrait.
  Cause: the click bubbled to the document-level
  *click-outside-to-close* handler **after** `renderMonitorSetupPopover()`
  rebuilt the `rotateBox` innerHTML and detached the clicked button —
  by the time the document handler ran, `popoverEl.contains(target)`
  was false. `stopPropagation()` in the rotate handler keeps the click
  contained.
- **Section-nav rail** now keeps the explicit click highlight on
  short cards near the bottom of the page (Profiles + Backup &
  Restore). The IntersectionObserver uses
  `rootMargin: -30% 0 -50% 0` — short cards never reach that
  centre band, so the click highlight was getting clobbered by
  the observer immediately. New `_navHighlightLockUntil` shared
  timestamp suppresses the observer for 700 ms around an explicit
  click; manual scrolling still works.
- **Header connection status** ("verbinde…" / "connected · Screen N")
  was stuck on the connecting placeholder for single-monitor
  setups. Cause: the page-load placeholder has
  `data-i18n="conn.connecting"` baked in; the WS `onopen` swapped
  the textContent to the dynamic *connected* string but left the
  attribute as-is. The first language switch from the bridge
  settings push then re-ran `applyI18n()` and snapped the text
  back to "verbinde…". Multi-monitor users dodged this because
  every tab-click reconnected the WS and re-ran `onopen` after
  the language had settled. Now `data-i18n` is re-set per WS
  state, and `setLanguage()` calls a new `_refreshConnText()`
  that picks the right key + parameters from `ws.readyState`.
- **Builder 4-step intro** lost the "declare any spans" step —
  span / orientation moved to the Configurator's per-tab gear
  in v1.2.10, the Builder no longer hosts that workflow.
  Wording now nudges users back to the Configurator for
  monitor topology.
- **Builder span-split** — inline auto-detect on file / library
  load. When the user picks an image for a wall tile and the
  image is significantly larger than the tile (≥1.5× in either
  dimension) **and** the tile is part of a multi-tile span, a
  dialog pops up: *"Image is X×Y, this tile is only x×y and is
  part of a {n}-tile span — spread across the whole span or
  keep it in just this tile?"*. The split path crops the source
  proportionally to each sibling tile's region within the
  bridge-screen composite (using each tile's `xOffset` /
  `yOffset` / `slotW` / `slotH`) and loads the per-tile crops
  into their `wallSlots`. Drop a 5120×1440 panorama on one half
  of a 2×2560×1440 span and each monitor receives its correct
  half — no per-tile right-click + menu hunt needed, no
  pre-cropping in an image editor. Works on both the File
  picker path and the Library tile picker; the canvas-load and
  current-bg paths skip the dialog (they're not span-target
  flows). A `triggerWallSplitSpanPick(idx)` programmatic entry
  point is kept around for future callers.

### Note — MP4 transparency for "glow through video"

Several users have asked whether a video wallpaper can let the
SignalRGB glow show through transparent regions, the way a PNG
with alpha does. **MP4 (H.264) has no alpha channel** — Glow
zones can only stack *on top of* an MP4, not show *through* it.
For animated wallpapers with glow showing through transparent
regions, the working formats are:

- **WebM with VP9-alpha**
  (`ffmpeg -i in.mov -c:v libvpx-vp9 -pix_fmt yuva420p out.webm`)
  — preferred, Chromium-based Lively / WE decode it natively.
- **APNG** — solid alpha support, but file sizes balloon vs WebM.
- **animated AVIF** — works in recent Chromium, smallest file
  size, but encoding tooling is still less common.
- **GIF** — 1-bit transparency only, so cutout edges look harsh;
  not recommended for glow effects.

This is a format limitation, not a wallpaper-page bug, so it
isn't something the bridge or page can work around.

## [1.2.12-beta] - 2026-05-28

> Beta: full page-side perf pass on the Matrix ambient effect after
> a tester reported it still felt choppy. Five layered fixes turn
> what was the most expensive ambient preset into the cheapest.

### Performance — Matrix ambient: full render pipeline rewrite

The Matrix ambient was the heaviest of the 12 ambient effects by
a wide margin. Five separate hotspots, fixed in one pass:

1. **Font + colour LUT hoisted to once-per-frame** via a new
   optional `before(ctx, tint)` hook on the preset (no behaviour
   change for the eleven other presets). The previous per-glyph
   code re-set the canvas font ("13px Consolas, …") and built a
   fresh `rgba(…)` / `hsla(…)` string per fill. The LUT is a
   16-bucket head + body colour table rebuilt only when the tint
   state changes.
2. **Integer Y position snapping** ([`y = (p.y - i * 16) | 0`]) —
   sub-pixel text positions force the browser to re-raster the
   glyph every frame instead of hitting the cached glyph atlas.
3. **`MATRIX_CHARSET` → `MATRIX_CHARS` Array**. Reading
   `MATRIX_CHARSET[idx]` indexes a string, which returns a freshly
   allocated 1-character string per access. With ~120 columns ×
   up to 20 chars built at every spawn plus ~6 Hz flicker swaps
   per column, that's thousands of one-shot strings per second —
   hidden allocator. Pre-splitting into an Array (interned string
   references) eliminates that.
4. **Particle pool + `respawn()` hook on Matrix**. Each Matrix
   column used to allocate a fresh `{x, y, speed, chars: new
   Array(len), …}` on every birth and the old struct went straight
   to GC on every death. With ~120 columns continuously dying
   and respawning, the GC churn produced the visible frame-time
   spikes that read as "choppy" even though steady-state CPU was
   moderate. The ambient module now maintains a per-preset
   recycle pool; presets that define `respawn(p, w, h)` get dead
   particles handed back to them for in-place re-initialisation.
   The Matrix `respawn` reuses the existing `chars` array
   (`.length = N`) instead of `new Array(N)`.
5. **`Array.splice` → swap-and-pop**. The compact-dead-particles
   pass used `particles.splice(i, 1)`, which shifts O(n) tail
   elements per dead particle. A burst of deaths in one frame
   degraded the step phase to O(n²). The new code swaps the dead
   slot with the tail and pops — order-independent (every preset
   z-orders its particles identically) and O(1) per death.
6. **Batch render by colour bucket** via a new optional
   `renderAll(ctx, particles, tint)` hook the ambient driver
   prefers when present. Chromium's `ctx.fillStyle = "…"` cache
   is a 1-entry LRU keyed on the previous value, so alternating
   between head and body colours per particle thrashes it — every
   write re-parses the CSS string. With ~2 000 glyphs per frame on
   a dense Matrix layer that's 2 000 colour re-parses. The new
   `renderAll` buckets every glyph into 32 lazy-allocated arrays
   (16 head + 16 body) keyed on the fade-LUT bucket, then draws
   each bucket with a single `fillStyle` assignment.

Combined: on a 3-screen 1440p Matrix-`dense` stress run,
`Lively.Player.WebView2` drops from **~12 % CPU pre-v1.2.12**
to **~1.5 % CPU** with all six fixes, and frame-time variance
(the source of the choppy feel) collapses to near-zero on the
JS-side because the per-frame allocator is no longer running a
2-3 ms minor-GC every ~500 ms.

### Performance — Zone-grid render path now Canvas-based + 30 Hz cap

After landing the Matrix rewrite above, the same tester reported
Matrix was *still* choppy under SignalRGB's *Crystal Glow* effect
(but smooth under the *Solid Color* effect). Diagnosis: Matrix
itself is fine; the bridge-frame render path was eating the main
thread. With Crystal Glow every zone changes every frame, so the
per-zone colour cache that v1.2.18 added (cheap when colours
don't change) buys nothing, and the wallpaper page hits its DOM-
mutation worst case: a 32×32 grid produces up to 1024 `.style.
background = "rgb(…)"` writes per frame, which at 60 Hz is 61 440
DOM style invalidations per second. Combined with the
`filter: blur()` on the grid container — which has to re-blur the
composited 1024-child layer every time any cell changes — the
main thread is saturated and Matrix's `requestAnimationFrame`
tick gets squeezed out.

Two coordinated fixes target the bridge render path directly:

7. **`renderFrame` capped at ~30 Hz.** The SignalRGB plugin
   sends UDP frames as fast as it can (~60 Hz typical). For a
   blurred glow layer 30 Hz is perceptually identical — the blur
   visually low-pass-filters the time domain too — and halving
   the render-rate frees the same amount of main-thread time for
   the ambient rAF + widget tick. Worst-case latency between an
   RGB change in SignalRGB and the glow on screen is one extra
   frame (~33 ms), well below the perception threshold for a
   wallpaper. Single five-line gate at the top of `renderFrame`,
   no API change.
8. **Grid layout now renders to `<canvas>` instead of N×M
   `<div>`s.** The DOM-grid path stays for the pills / stripes /
   off layouts (their zone counts are low and they rely on
   per-zone CSS like `border-radius`, `box-shadow` and
   `transition` that don't translate to canvas). The grid layout
   gets a new `<canvas id="bars-canvas">` sibling to `#bars`. Its
   internal pixel size is the SignalRGB grid resolution
   (typically 32×32 = ~4 KiB); CSS scales it to fill the viewport
   and the `filter: blur()` runs on a single flat texture instead
   of a 1024-child layer. The render path becomes:

   - copy RGB bytes from the UDP buffer into a reused
     `ImageData` lane (alpha pre-set to 255 at allocation)
   - `putImageData(_, 0, 0)`

   That's one `putImageData` per frame instead of up to 1024
   `style.background` writes. The browser does the upscale +
   blur on the GPU. Visually identical (the blur dominates the
   smoothing either way). The per-zone colour cache that the
   DOM path needed is no longer relevant — writing all 4 KiB
   unconditionally is cheaper than reading + comparing them
   first.

Expected on a 3-monitor Crystal Glow setup: Matrix runs smooth
through Crystal Glow, and the wallpaper-page CPU drops ~50–70 %
when Crystal Glow is active. The pills / stripes layouts are
unchanged in both visuals and code path.

### Changed — grid renderer made opt-in (default: DOM)

A tester on an RTX 4070 Ti reported GPU usage rising from
~10-13 % to ~20-25 % after the canvas-grid switch landed. Root
cause: the canvas path hands the GPU a 32×32 source texture that
the compositor then has to bilinear-upsample to a 4 K viewport
*and* run the blur filter over the result. Chromium has a much
faster solid-rectangle fast-path for the DOM-grid composite, so
for users whose CPU is fine but whose GPU is precious (e.g.
dGPU-rich gaming rigs) the trade is the wrong direction.

The canvas path is therefore now **opt-in** via a per-screen
`gridRenderer` setting in the Configurator → Glow card:

- **DOM (lower GPU)** — the original solid-rectangle path with
  the v1.2.18 per-zone colour cache. Default.
- **Canvas (lower CPU)** — the v1.2.12 first-pass implementation.
  Recommended for users on weak CPUs running heavy every-zone-
  every-frame SignalRGB effects (Crystal Glow, full-grid Audio
  Reactive, …) who can afford a small GPU bump.

The 30 Hz render cap above stays on for both paths — that one
helps CPU **and** GPU equally and has no perceptual cost.

### Fixed — Pause leaving ~10 % GPU on (rAF kept compositor warm)

A tester reported that the tray's *Pause glow + animations* dropped
JS-CPU to ~0 % as expected but left the Lively / WE WebView2 GPU
load at ~10 %. Diagnosis: all four rAF loops (ambient, audio-glow,
pixelfx, parallax) scheduled the next frame **before** checking
`isPaused`, so even while paused the browser had `requestAnimationFrame`
firing at 60 Hz. The callback returned immediately (JS cost ≈ 0),
but every rAF wakes WebView2's compositor — which then re-evaluates
every `filter: blur(…)` and canvas filter on the static layers because
the compositor can't tell that the source pixels haven't changed.
End result: GPU spinning at ~10 % drawing pixels identical to the
last frame, forever.

Pure rAF cancellation is brittle (each module would need a
resume-from-paused hook), so the fix targets the actual cost: when
paused, the four heavy filter layers (`#bars`, `#bars-canvas`,
`#ambient-canvas`, `#audioglow-canvas`, `#pixelfx-canvas`) are
removed from the compositor entirely via `display: none` on a new
`body.paused-glow` class. Background image, widgets and the
"PAUSED" badge stay visible — pause means "stop the glow + motion",
not "black screen". GPU drops to compositor-idle (~0 % on the
gaming-class GPUs that surfaced the regression).

The rAF early-return is kept as a JS-side hygiene measure (no
useless work even though the cost was ~0).

### Performance — Glass-tile `backdrop-filter` + rAF cancel-on-pause

After the layer-hide fix above the same tester reported the GPU
fluctuated between 3 - 9 % in pause mode, hinting at something
larger that also costs in non-pause. Two structural finds:

1. **`backdrop-filter: blur(12 px) saturate(140 %)`** on every widget
   with the *Glass* tile style. Backdrop-filter is the single most
   expensive GPU op on the page — the GPU must re-sample the pixels
   *behind* the widget rect, run a Gaussian-blur convolution, apply
   the saturation matrix, and composite. The cost scales with
   kernel-size²: a 12 px kernel reads ~49 texels per output pixel,
   a 6 px kernel reads ~13. With Crystal Glow's every-zone-every-
   frame source on a 3-monitor setup with 8 glass widgets, that's
   ~2.9 billion texture fetches/sec just for backdrop-filter passes.

   Blur radius dropped from **12 px → 6 px** (visual difference at
   wallpaper viewing distance is minor; the saturation lift keeps
   the "glassy" feel). Two CSS hints added on the same rule:
   - `contain: paint` scopes the dirty area so a widget animation
     (clock seconds tick, etc.) can't invalidate paint of its
     neighbours.
   - `will-change: backdrop-filter` tells the compositor to keep a
     cached blur texture per widget so a static source frame
     doesn't recompute the blur on every rAF wakeup.

2. **rAF chains kept scheduling on pause.** All four animation
   loops (ambient / audio-glow / pixelfx / parallax) called
   `requestAnimationFrame(tick)` *before* the `isPaused` check, so
   every frame the JS callback fired, early-returned, and rescheduled
   — kept WebView2's compositor warm at 60 Hz on hidden layers
   forever. Now each tick stops the chain (`raf = null`) the moment
   `isPaused` flips true, and a window-level `wallpaper-resume`
   event dispatched from `_recomputePaused` rearms the four chains
   on unpause via per-module listeners.

Combined with the layer-hide fix from the previous entry, pause
mode now sits at compositor-idle GPU on the RTX 4070 Ti setup
that surfaced the regression, and non-pause Glass-tile load drops
because the backdrop-filter cost is amortised away.

### Added — Glass quality per-screen setting (low / medium / high)

Closes the loop on backdrop-filter for users at either end of the
GPU spectrum:

- **Low** — `backdrop-filter: none`, slightly higher background
  alpha so the tile still reads. Biggest GPU win. Visual is solid-
  tinted rather than glassy.
- **Medium** (default) — `blur(6 px) saturate(140 %)`. The
  rebalanced v1.2.12 default.
- **High** — `blur(12 px) saturate(140 %)`. Restores pre-v1.2.12
  visual fidelity for users on heavy GPUs who want the original
  frosted look.

Surfaced as a `Glass quality` dropdown in the Configurator → Glow
card, just below `Grid renderer`. Only takes effect on widgets
that opted into the Glass tile style.

### Hardened — Tray updater: `ping` → `timeout` + 40 s budget

Two small hardenings to the v1.2.11 cmd-launcher relaunch path:

- Replaced `ping -n N 127.0.0.1 >NUL` with `timeout /t N /nobreak >NUL`.
  Both binaries live in `System32`, but some Defender ASR profiles
  treat a parent-spawned `ping.exe` as a network-probe heuristic
  and block / log it; `timeout` has no network surface and clears
  those rules.
- Bumped the pre-relaunch wait from 25 s → 40 s. The extra window
  absorbs slow disks + AV real-time-scan of the freshly-replaced
  exe before `start` fires. Fallback if the wait still isn't
  enough is the existing `HKCU…\Run` autostart entry, which fires
  at the next Windows login.

### Performance — Misc hygiene

- `ensureZones` early-returns when the grid layout is in canvas-
  render mode. Pre-fix, the page built 1024 invisible `<div>` zones
  every grid-size change even though the canvas path never reads
  them.
- `_anyTintedWidget()` (called from `renderFrame` every tick) now
  caches its boolean and is invalidated from every widget mutation
  path. Was a linear scan over `widgetNodes` 30 ×/s on the renderer
  fast-path.

### Added — Wallpaper-bundle / bridge version handshake + stale-bundle banner

Lively + Wallpaper Engine import the wallpaper bundle as a *snapshot*
— Lively caches the ZIP under a random-hash folder, WE Workshop is
on its own publishing cycle. So a user who updates the bridge via
the tray's auto-update doesn't automatically get the matching new
wallpaper-page JS, and they had no way to spot the drift short of
noticing missing features.

This release closes the loop:

- `installer/build.ps1` stamps the bridge version into the
  wallpaper bundle's `index.html` at staging time (replaces a new
  `__WALLPAPER_VERSION__` placeholder in a `<meta>` tag). Lively
  ZIPs + the WE single-bundle both get the same stamp.
- On WS connect the wallpaper page sends `{type:"hello",
  wallpaperVersion:"1.2.X"}`. The bridge's WS loop compares against
  `APP_VERSION` using the same `_parse_version` semver helper the
  update checker already uses, and on a *strictly older* bundle
  pushes `{type:"version-mismatch", bridge:…, wallpaper:…}` back on
  the same writer. Same-version and newer bundles get no banner.
- The wallpaper page renders a subdued amber banner bottom-right:
  *"Wallpaper bundle out of date. Bridge: 1.2.12 · Wallpaper:
  1.2.5. Open the tray menu → Re-import wallpaper bundles (or
  Configurator → System) and re-add the wallpaper in Lively / WE."*
  Pointer-events: none, so it never eats wallpaper-host input.
- The Re-import button in Configurator → System has been wired
  since v1.2.1; the banner just funnels users to it.

When the page is served from the dev tree (no installer stamp),
the meta tag still says `__WALLPAPER_VERSION__` and the page
reports `"dev"`. The bridge short-circuits that case — no banner —
so local development can drift from `APP_VERSION` freely.

### Added — `Frame rate` setting (Performance / Balanced / Quality)

The 30 Hz cap is now user-tunable, paired with a read-only plugin
send-rate readout. New per-screen `frameRate` setting (Configurator
→ Glow card) with three buckets:

- **Performance — 20 Hz** — biggest CPU/GPU win on weak hardware.
- **Balanced — 30 Hz** (default) — perceptually identical to 60 Hz
  on the blurred glow layer, half the work.
- **Quality — 60 Hz** — matches the plugin's typical max rate.

Both ends of the pipeline read the same value: the bridge's
`Broadcaster.broadcast_frame` caps outgoing per-screen at this
rate, the wallpaper page's `renderFrame` caps at the same. So no
WS frame ever crosses that the page would just drop. Joins
`gridRenderer` + `glassQuality` in `_BUNDLE_FORBIDDEN_KEYS` — Look
bundles can't override a hardware preference.

Next to the dropdown, the Configurator surfaces a live readout of
the active screen's *actual* incoming plugin rate
("plugin: 165 fps") via a new `measuredPluginFps` field in
`/config`. The `UdpReceiver` counts inbound frames per screen in
a 1 s sliding window and the Configurator's existing 5 s
`/config` poll keeps it fresh. Useful for picking a cap that
matches the workload without guessing — a 165 fps Solid Color
benefits a lot from the 20 Hz Performance cap.

### Performance — Bridge-side 30 Hz broadcast cap

Same tester reported the wallpaper page was at ~10 % CPU even with
*Solid Color* active in SignalRGB (not Crystal Glow), where the
per-zone colour cache should hit 100 % and the renderFrame body
does almost no work. Diagnosis: the SignalRGB plugin sends UDP at
the rate it can compute frames — for cheap effects (Solid Color,
simple gradients) that's often 150–200 fps. The bridge relayed
every one of those, the wallpaper page received them as WS
messages, allocated a `Uint8Array` view, fired `onmessage`, and
*then* the 30 Hz renderFrame cap dropped 80 % of them. The per-
frame WebView2 work (WS decode + dispatch + the Uint8Array view
construction) dominated the actual paint.

Added a matching 30 Hz cap on `Broadcaster.broadcast_frame` itself,
keyed per screen. Effective outgoing rate is now 30 Hz max
regardless of how fast the plugin is sending; the wallpaper page
sees one frame per render cycle instead of 5–6.

### Performance — pause-detect rAF probe throttled 60 Hz → ~5 Hz

A tester reported the wallpaper-page CPU baseline was ~10 % vs
~3 % for other Lively wallpapers, and Lively's pause-mode CPU
spiked 1-7 % even with nothing on screen. Root cause: the
`probeRafLoop` that detects when Lively or the OS pauses our page
was running at the page's full rAF rate (~60 Hz) just to take a
timestamp on every frame. Even with an empty callback body, the
chain of `requestAnimationFrame` calls keeps WebView2's compositor
warm continuously.

Throttled the probe via a `setTimeout(…, 200) → requestAnimationFrame`
cascade. Effective rAF rate drops from ~60 Hz to ~5 Hz, which still
distinguishes a paused page (rAF doesn't fire at all → timestamp
freezes → the 250 ms setInterval consumer sees >500 ms staleness)
from a running one. Saves the bulk of the idle baseline.

### Performance — Standby card no longer burns ~20 % GPU on its own

A tester reported that with **no widgets placed and the bridge not
running** Lively was still sitting at ~20 % GPU. With the bridge
disconnected the only thing on screen is the standby card
(`"SignalRGB Wallpaper Bridge offline — Start SignalRGBBridge.exe"`),
which carried two expensive CSS habits:

- A `backdrop-filter: blur(14 px) saturate(140 %)` on the card
  itself — per-frame re-blur of the wallpaper underneath the
  ~400×220 px card area, burning ~10-15 % GPU continuously.
  Dropped; background opacity bumped from `0.78` → `0.94` so the
  card still reads as a "frosted" surface without the blur cost.
- The pulsing-ring animation on the standby icon used
  `@keyframes` on `box-shadow` (`0 px → 14 px → 0 px` spread).
  `box-shadow` animations are *paint* operations — the browser
  re-rasterises the element on every keyframe interpolation step.
  Moved the pulse to a `::after` pseudo-element and switched the
  animated property to `transform: scale + opacity`, which stay
  on the compositor and cost essentially nothing.

The card stays visible with the same text and the same visual
rhythm (slow scan line + pulsing icon ring); the bridge-not-
running state now sits at compositor-idle GPU instead of ~20 %.

### Hardened — Look bundles can no longer override perf prefs

`quick_look_apply` filters `gridRenderer` and `glassQuality` out
of incoming bundle settings. These are *user* hardware preferences;
a cosmetic "Cyberpunk Vibes"-style Look shouldn't be flipping the
DOM/Canvas renderer or killing the glass blur just because the
bundle author happened to have a strong CPU + weak GPU. Two new
keys join `widgets` / `mirrorOf` / `cycle` as bundle-forbidden.

## [1.2.11-beta] - 2026-05-28

> Beta: makes the **tray's "Download + install update"** flow
> robust. A user hit the "Failed to load Python DLL python313.dll"
> error again — but only after the tray-triggered silent update,
> not on fresh installs or on manual launch from the Start menu.
> Two coordinated fixes target both halves of the failure mode
> (DLL load + the new bridge not coming up afterwards).

### Fixed — DLL load failure + missing auto-restart after tray update

Symptom: after `Tray → Updates → Download + install update`, the
post-install Inno `[Run]` step popped a *"Failed to load Python
DLL `…\_MEI…\python313.dll`. LoadLibrary: The specified module
could not be found"* dialog and the new bridge never started.
Starting the bridge manually from the Start menu worked. Diagnosis:
the bundled DLLs (including the v1.2.6 vcruntime fix) are correct,
but Inno's `[Run]` launches the bridge in a token / process-
ancestry context that on some AV / EDR / Controlled-Folder-Access
setups refuses `LoadLibrary` on `%TEMP%\_MEI<random>\` — the
PyInstaller `--onefile` extraction dir.

Fix is two-layered:

**Layer 1: structural.** PyInstaller switched from `--onefile` to
`--onedir`. The bundle is now a directory under `{app}\` containing
`SignalRGBBridge.exe` + `_internal\` (python313.dll, vcruntime,
.pyd extension modules, HTML/CSS data files). There is no
extraction step at launch and no temp directory involved — the OS
loader resolves DLL dependencies straight from the install dir, so
the `%TEMP%` LoadLibrary failure mode is removed entirely. Side-
effect bonus: bridge startup is ~2x faster (no 8000-file extract
per launch).

**Layer 2: launch path.** The tray's `_download_install_worker`
now drops `autostart` from the silent installer's `/MERGETASKS`
string — so Inno's `[Run]` won't try to launch the bridge in its
own context — and instead spawns a detached `cmd.exe` child of the
*current* bridge process to schedule the relaunch ~25 s later
(`ping -n 26 127.0.0.1 >NUL && start "" /B "<exe>"`). The cmd
inherits the bridge's user-context token (`CREATE_BREAKAWAY_FROM_JOB`
keeps it alive after the bridge's `os._exit`), so the new bridge
launches as a normal user process — no Inno-context contamination,
no AV gate. The Registry autostart entry still installs, so the
bridge also comes up cleanly at the next Windows login.

### Migration notes

Existing v1.2.6 → v1.2.10 installs that upgrade to v1.2.11 will
see a small layout change in their install directory: the
`_internal\` subfolder appears next to `SignalRGBBridge.exe`. The
exe path stays identical (`{app}\SignalRGBBridge.exe`), so Start-
menu shortcuts, the Registry autostart entry, the Lively / WE
bundle paths and the SignalRGB plugin are all unaffected.

## [1.2.10-beta] - 2026-05-28

> Beta: the permanent-fix candidate that supersedes the v1.2.9
> diagnostic build. Now-Playing / SMTC is **re-enabled** but the
> idle-gate on every poller is now widget-aware — pollers only
> fire when a widget that consumes their data is actually placed
> somewhere. Zero cost when nothing reads the data, even with the
> wallpaper page running.

### Hardened — Widget-aware poller idle-gate

User observed their v1.2.6 leak surfaced after a 12 h run with
**no widgets configured at all**. v1.2.8's idle-gate was too loose
to catch that case: it only checked "is a wallpaper page
connected?" and the answer was yes (Lively was running), so the
SMTC / LHM / sysstats pollers continued their 1 Hz IPC chain —
into receivers (NPSMSvc → Spotify → DWM → WebView2) that nobody
on our end was even consuming.

v1.2.10 tightens the gate. A new `BridgeRuntime.placed_widget_types()`
returns the set of widget-type strings currently placed across
all screens; each poller gets a closure that returns True iff
at least one client is connected AND at least one widget in its
"served types" set is placed.

| Poller            | Polls when these widgets are placed |
| ----------------- | ----------------------------------- |
| `NowPlayingPoller`| `now-playing` |
| `HwMonPoller`     | `hardware-sensor` |
| `SysStatsPoller`  | `cpu-meter` / `ram-meter` / `hardware-sensor` / `now-playing` |

Pure-client widgets (clock, calendar, sticky-note, countdown,
picture-frame, quote, weather, rss, audio-spectrum) need no
backend data so no poller fires for them. A user with only those
placed sees the bridge sit at essentially zero CPU + flat memory
no matter how long Lively / WE runs.

### Changed — `ENABLE_NOWPLAYING` defaults back to True

The v1.2.9 hard-kill-switch is kept (flip to False to re-arm
the diagnostic build) but defaults to True now that the proper
fix is wired up. Existing v1.2.9 installs that confirmed the
SMTC cascade was the source should move to v1.2.10 to get the
feature back — it'll only fire when actually needed.

## [1.2.9-beta] - 2026-05-28

> Diagnostic beta. Same hardening as v1.2.8 **plus** the entire
> Now-Playing / SMTC code path is hard-disabled, so the user
> reporting the 12 h memory build-up can run with this for a day
> and tell us whether the SMTC cascade
> (Bridge → NPSMSvc → Spotify → DWM → WebView2) was the source.

### Changed — Now-Playing feature fully removed (diagnostic build)

A new `ENABLE_NOWPLAYING = False` constant at the top of `bridge.py`
gates every SMTC touchpoint:

- `NowPlayingPoller` is never constructed. No `winrt` import, no
  `SMTCManager` handle, no 1 Hz IPC roundtrip.
- The `now-playing` widget type is removed from `WIDGET_DEFAULTS`
  on startup, so the palette in Configurator + Builder hides it
  and any incoming `widget-add` for that type is silently rejected.
- `SysStatsPoller` is passed `nowplaying=None`, so its 1 Hz
  JSON push omits the `nowPlaying` field entirely.

Persisted config is **not** mutated — existing now-playing widget
entries stay in the JSON, the page just never receives data and
renders the widget's idle placeholder. Flip the constant back to
`True` and rebuild to restore.

If 12 h with v1.2.9 stays flat: confirmed the SMTC cascade was
the source, and the v1.2.8 manager-cache + idle-gate is the right
permanent fix. If v1.2.9 still grows: the suspect is somewhere
else and we have a much narrower set of suspects to look at.

## [1.2.8-beta] - 2026-05-28

> Beta: continues the v1.2.7 leak hunt with three targeted fixes after
> the user spotted that NPSMSvc / Spotify / DWM / WebView2 all spike
> together when the bridge is under stress — the *cascade* is the load,
> not just our process.

### Hardened — Widget-command thread spawn replaced with executor pool

`_on_widget_command` used to `threading.Thread(target=run).start()`
for every WS message — `widget-update`, `setting-update`,
`viewport`, `quick-look-apply`, `widgets-set`, the lot. A single
Builder per-tile drag fires 60-100 `widget-update` frames; a slider
in the Configurator fires `setting-update` at the same rate; Quick
Looks bundles cascade through `widgets-set` + `setting-update` +
`preset-save`. Over a 12 h session that meant thousands of
short-lived OS threads. They exited cleanly (daemon=True) but
Windows commits thread stack pages lazily and the high-water marks
accumulate in the process commit charge, plus each thread's run()
closure pinned the message dict + the deep-copied config in
`_mutate_screen` until the disk write returned (slow under OneDrive
sync). The handler now submits to the asyncio loop's default
ThreadPoolExecutor (~32 workers, recycled) which preserves the
off-loop file-write isolation but caps thread count.

### Hardened — SMTC manager cached + idle-gated

`NowPlayingPoller._tick` called
`GlobalSystemMediaTransportControlsSessionManager.request_async()`
every second. The WinRT spec says this returns a singleton, but the
COM ref-counting in the winrt-Python bindings isn't always clean on
repeated calls, and each call triggers an IPC roundtrip
Bridge → NPSMSvc → registered media app (Spotify, Edge, Groove, …)
that the receiving app responds to by re-marshalling its metadata
and cover art. The user observed all four
(NPSMSvc / Spotify / DWM / WebView2) spiking together when the bridge
was hot — confirming the cascade.

The poller now resolves the manager exactly once on the first tick
and reuses the cached reference on every subsequent tick. The
visible knock-on for the user is the Task Manager "red" group going
quiet outside of actual track changes.

### Hardened — Pollers skip work when no wallpaper page is connected

`NowPlayingPoller`, `HwMonPoller` and `SysStatsPoller` previously
polled (and pushed) at their 1 Hz cadence forever regardless of
whether a wallpaper page was connected to consume the snapshot.
Closing Lively / Wallpaper Engine left the bridge driving an IPC
load nobody could observe. All three now check
`Broadcaster.has_any_clients()` (lock-free dict-values scan) before
the expensive part of each tick and short-circuit when nothing is
connected. The HwMon snapshot from the last successful poll is kept
so the Configurator's `/hwmon/sensors` HTTP picker still returns
something useful when a user opens the picker without an active
wallpaper.

## [1.2.7-beta] - 2026-05-28

> Beta: same "high CPU + ~556 MB after 12 h" pattern resurfaced for a
> user even on top of v1.2.1's per-frame backpressure fix. This beta
> hardens the bridge's relay loop so the bridge stops doing per-frame
> work when nobody's listening, brings the other `push_*` channels in
> line with the broadcaster's backpressure, and adds a periodic GC +
> diag heartbeat so the next report can pinpoint exactly which counter
> moves.

### Hardened — Bridge no longer encodes / schedules per-frame work when paused or no clients

`UdpReceiver.datagram_received` previously created an `asyncio.Task` for
every inbound UDP frame and let `broadcast_frame` decide whether to
short-circuit (paused / no clients). With the SignalRGB plugin pushing
60+ Hz × N screens forever regardless of bridge state, that meant
~120+ throwaway tasks per second over a 12 h session — each one
allocates a coroutine, a future, and (when it ran) a fresh
`encode_binary_frame` bytes object. Tasks completed quickly so the
*reachable* set stayed bounded, but the constant churn fragments
CPython's pymalloc heap; arenas allocated during bursty load aren't
reliably returned to the OS, so process RSS drifts up over hours even
without a true reference leak.

v1.2.7 gates the work in `datagram_received` itself (sync, on the
selector thread): if `get_paused()` is True or `has_clients_for(screen)`
returns false, the datagram is dropped before any task is created and
before any frame buffer is allocated. The plugin keeps sending; the
bridge silently absorbs.

### Hardened — `push_sysstats` / `push_pause` / `push_reload_all` / `push_settings` now share broadcaster backpressure

`broadcast_frame` got per-client write-buffer backpressure in v1.2.1
(skip-when-buffer > 256 KiB) but the other four push channels still
wrote unconditionally. None of them are high-rate so the bound was
small, but a slow / wedged client would let the `StreamWriter`'s
internal buffer grow uncapped on each tick of sysstats forever. All
four channels now read `transport.get_write_buffer_size()` and skip
the write when over the cap. They also snapshot the client list and
early-return without encoding JSON when no clients are connected — a
small per-second CPU win for the headless-bridge case.

### Added — Periodic `gc.collect()` + diagnostic heartbeat

A daemon task on the bridge's asyncio loop runs `gc.collect()` every
60 s to nudge generation-2 collection to release empty arenas back to
the OS, and once every 5 minutes prints one `[diag]` log line with
the process RSS, live asyncio task count, connected client count, and
in-flight chunked-frame partials. Cost is negligible (a forced GC on
an idle Python heap is sub-ms) and the heartbeat lets the next
diagnostics export carry a memory-curve over time so we can attribute
any future drift to a specific counter rather than guessing again.

## [1.2.6-beta] - 2026-05-26

> Beta: fixes the "Failed to load Python DLL" install error some users
> hit, plus a deep dive that found video screen-backgrounds were
> broken end-to-end since v1.2.0 + a couple of latent bridge issues.

### Fixed — "Failed to load Python DLL python313.dll" on some machines

A user hit `Failed to load Python DLL ...python313.dll. LoadLibrary:
The specified module could not be found.` on the update launch. The
misleading message actually means a *dependency* of python313.dll —
the MSVC runtime (`vcruntime140.dll` / `vcruntime140_1.dll`) — wasn't
found. The bridge is built from the Microsoft Store Python, and
PyInstaller doesn't reliably pull those DLLs into the `--onefile`
bundle from that Python distribution (they live in System32 on the
build machine so the local exe runs fine, masking it). Users without
the VC++ 2015-2022 Redistributable then hit the error.

`build.ps1` now explicitly `--add-binary`s `vcruntime140.dll` +
`vcruntime140_1.dll` from System32 into the bundle, so they're always
present regardless of the build Python or the user's installed
runtimes.

### Fixed — Video screen-backgrounds were broken end-to-end (since v1.2.0)

Two latent bugs in the v1.2.0 "video backgrounds" feature, only
reachable for video set as a *screen* background (the live-preview
+ Builder path):

1. **`_update_background` saved every upload as `.png`** regardless
   of content, so an MP4 landed as `screen-N-<ms>.png`. The wallpaper
   page's video detection (`VIDEO_BG_EXTS`) keys off the URL
   extension → it never recognised the file as a video and tried to
   paint it as a still. v1.2.6 magic-byte-sniffs the upload and saves
   the real extension (`.mp4` / `.webm` / `.mov` / `.m4v` / `.mkv`).
2. **The `/image` proxy rejected video extensions with 415** and had
   no HTTP Range support. Browsers require `206 Partial Content`
   range responses to play a `<video>` from a URL. v1.2.6 rewrites
   the proxy: serves video MIME types, honours single-range
   requests with a proper `206` + `Content-Range`, advertises
   `Accept-Ranges: bytes`, and **streams in 256 KiB chunks** instead
   of reading the whole file into RAM (a 300 MB video bg used to
   spike the bridge's memory 300 MB per request).

### Fixed — Unbounded WebSocket client frame could OOM the bridge

`read_client_text_frame` read whatever payload length the client's
frame header claimed — up to 2^64 bytes via the 8-byte length field
— with no cap. A bug or a malicious local client could make
`readexactly(n)` try to buffer multiple GB. v1.2.6 caps client text
frames at 4 MiB (the largest legitimate message, a 4-monitor
widgets array, is a few KB) and drops the connection on anything
larger.

---

## [1.2.5] - 2026-05-26

> Critical pause-handling fix. The tray "Pause" toggle, the bridge's
> fullscreen-auto-pause, and `document.visibilitychange` all worked
> *for ~250 ms* and then silently un-paused themselves — the rAF
> probe was overriding any external pause every interval tick.

### Fixed — Manual / fullscreen pause un-paused itself after 250 ms

The wallpaper page had a `setInterval` probe that watches the rAF
tick rate to auto-detect when Lively / the OS has suspended
rendering (Lively's "pause-on-fullscreen" works by suspending
WebView2 at the OS level). When the probe saw rAF ticking
normally, it called `setPaused(false)` — which clobbered the
state any external source (tray, bridge fullscreen-watcher,
visibilitychange) had just set to true.

User-visible symptom: clicking "Pause glow + animations" in the
tray showed the PAUSED badge briefly, then everything resumed
on its own. Same for the bridge's fullscreen-pause hook —
worked on Lively builds that suspend WebView2 (because rAF
actually stopped), failed on builds that don't suspend (because
the probe overrode our pause).

v1.2.5 splits the pause state into two slots:

- `_externalPaused` — set by the bridge WS `paused` message,
  Lively's `livelyWallpaperPlaybackChanged` callback, and
  `document.visibilitychange`. Persistent until externally cleared.
- `_renderingPaused` — set by the rAF probe only.

Effective `isPaused` is the OR of both. The rAF probe never
touches `_externalPaused`, so manual + auto pauses now stick.

### Fixed — Audio-glow kept animating during pause

The audio-glow canvas's `tick()` was the only rAF render loop in
the wallpaper page that missed the `if (isPaused) return;` guard.
Pre-v1.2.5 the spectrum / waveform / pulse animation kept
running on top of an otherwise frozen wallpaper. v1.2.5 adds
the guard.

### Fixed — Background video kept playing during pause

`<video id="bg-video" autoplay loop>` kept playing during a
manual / fullscreen pause. v1.2.5 calls `bgVideoEl.pause()` /
`.play()` from the central `_recomputePaused()` helper so a
video bg actually freezes when the wallpaper is paused (and
resumes on un-pause).

---

## [1.2.4] - 2026-05-26

> Configurator tour positioning fix + Rotate/Flip moved to the
> always-visible canvas toolbar.

### Fixed — Configurator tour landed off-screen on tall cards

Even after v1.2.3's expand + clamp, steps 6 / 7 / 8 (Background,
Widgets, Presets) still placed the tooltip way down or off the
viewport. Root cause: `window.scrollTo({behavior: "smooth"})`
followed by a fixed-timeout measurement. Smooth scrolls routinely
take longer than the 320 ms timeout, so the rect we measured was
still at the *pre-scroll* position → spotlight + tooltip both
landed wrong.

v1.2.4 switches the scroll to instant (`behavior` omitted),
measures across two `requestAnimationFrame`s (scroll + expand
reflow → measure on the settled layout), and rewrites the tooltip
placement as a candidate-fallback chain:

1. Right of the spotlight
2. Left of the spotlight
3. Below it
4. Above it
5. **Fallback**: pinned to the bottom-right corner of the viewport
   (this catches the "spotlight fills the whole viewport" case
   that broke step 6/7 — a tall Background or Widgets card).

Every candidate is clamped to a 10 px viewport margin, so the
tooltip can never go off-screen.

### Changed — Rotate / Flip moved to the canvas toolbar

v1.2.3 added ⇄ Flip H / ⇅ Flip V next to Rotate in the Load
section — but that section is `simple-hide`'d in Simple mode, so
the buttons were invisible exactly when users wanted them (during
in-place slot editing). v1.2.4 moves all three transform icons
(⟳ ⇄ ⇅) into the canvas-toolbar (next to the zoom controls),
always visible regardless of mode.

---

## [1.2.3] - 2026-05-26

> Batch of UX fixes from a test session: manual pause in the tray, a
> working Configurator tour, a Builder tour button, the threshold-
> slider scrollbar, and image flip/mirror in the Builder.

### Added — Tray Pause / Resume

New "Pause glow + animations" entry in the tray menu, independent
of the fullscreen auto-pause. Freezes glow + ambient + widget
animation on every screen on demand — handy for saving GPU while
AFK without launching a fullscreen app. Checkmark reflects the
current manual state. Effective pause = fullscreen-auto OR manual,
so a manual resume doesn't override an active fullscreen pause.

### Added — Image flip / mirror in the Builder

New ⇄ Flip H and ⇅ Flip V buttons next to Rotate in the Load
section. Mirrors the canvas left↔right or top↕bottom — built for
the "same image flipped across two monitors" look. Flip bakes the
current canvas (including transparency cuts) into a fresh source
and resets the edit stack, so it's best used early. (Advanced-mode
section; switch from Simple if you don't see it.)

### Added — Builder tour + Tour button

The Builder gained a first-run tour in v1.2.2 but no way to replay
it. v1.2.3 adds a "Tour" button in the Builder header that re-runs
the 7-step walkthrough any time.

### Fixed — Configurator tour landed off-screen on collapsed cards

The tour's later steps (Presets, System) spotlighted collapsed
section cards — the highlight ring was a 1-line sliver and the
tooltip jumped off the bottom of the viewport. v1.2.3:

- Expands the target card (removes `.collapsed`) before measuring,
  so the spotlight covers the real content.
- Scrolls the target near the top of the viewport (offset for the
  sticky header + tab row) instead of centring it.
- Clamps the spotlight height to the viewport so a tall card can't
  push the ring + tooltip off-screen.

### Fixed — Builder tool-options panel showed a horizontal scrollbar

Range sliders have an intrinsic ~129px min-width that flexbox won't
shrink without `min-width: 0`. In the 260px tool-options column the
label + slider + value row overflowed → horizontal scrollbar (the
value behind "Tolerance" was the visible symptom). v1.2.3 adds
`min-width: 0` to the slider + select, trims the label / value
widths, and sets `overflow-x: hidden` on the panel.

### Investigated — LibreHardwareMonitor DLL instead of REST server

Requested: drop the "install LHM + enable its Remote Web Server"
step by loading `LibreHardwareMonitorLib.dll` directly. **Verdict:
not worth it.** The DLL needs the WinRing0 kernel driver for most
sensors (CPU temps, voltages), which forces admin elevation — that
breaks the bridge's no-admin install promise, a worse UX than
"install LHM once". It'd also pull in pythonnet + the .NET runtime
(fragile under PyInstaller) and add MPL-2.0 source-availability
obligations. The current REST approach stays.

---

## [1.2.2] - 2026-05-26

> Polish + doc refresh on top of v1.2.1. Fixes the "Load current
> background" duplication on span screens, refreshes the Configurator
> tour for the v1.2 UI, adds a brand-new Builder tour for the
> monitor-wall-first flow, and condenses 4500 lines of CHANGELOG
> down to a navigable 850.

### Fixed — "Load current background" duplicated the full bg into both span tiles

When a bridge screen was declared as a 2-monitor span, clicking
"Load this screen's current background" on either sub-tile pulled
in the full bridge-resolution image (5120 × 1440 in the classic
ultrawide example) and stuffed it into the tile's slot. Editing
the left tile then showed the whole panorama instead of just its
2560-wide left half.

v1.2.2 cover-fits the source image onto the bridge rectangle the
same way the wallpaper page does at render time, then slices out
only the sub-tile's `(xOffset, yOffset, slotW, slotH)` region
before staging the slot. So left-tile shows the left half,
right-tile shows the right half. Single-tile screens go through
the unchanged fast path.

### Added — First-run Builder tour

The Builder didn't have a tour before. New users opened it,
stared at the panel grid, and most never discovered the
monitor-wall-first workflow. v1.2.2 ships a 7-step overlay +
spotlight tour mirroring the Configurator's pattern:

1. Welcome
2. Simple / Advanced mode toggle
3. Monitor-Setup read-only summary
4. Monitor Wall tiles
5. Edit canvas
6. Tool toolbox (Click-pixel, Auto-Cut, brushes)
7. Apply Wall

Fires once per browser via `signalrgb.builder.tour_seen`. Replay
via DevTools localStorage clear, or call `startBuilderTour()`
from the console.

### Changed — Configurator tour refreshed for the v1.2 UI

The pre-v1.2 tour pointed at UI that's since been moved or
removed (single shared "Screen settings" trigger, the standalone
Overview card on single-monitor setups). v1.2.2 rewrites the
step list to cover: screen tabs → per-tab settings gear → section
nav rail → Quick Looks → Background → Widgets → Presets → System
section → Builder shortcut → Done. Tour body text mentions
Monitor-Setup span declarations, video backgrounds, RSS widget,
auto-snapshot on Quick Look apply, and Diagnostics export.

### Changed — CHANGELOG cleanup

The active `CHANGELOG.md` was 4523 lines / 92 release headers.
v1.2.2 archives pre-v1.0 entries (51 betas covering the v0.x
foundation work) into `docs/CHANGELOG-archive.md` and condenses
the 18 v1.2.x-beta entries into a single one-line-per-beta index
block. The full per-beta entries stay in git history under their
tags (`git show v1.2.5-beta` etc.). Active CHANGELOG is now ~850
lines / 12 headers.

### Other

- README updated to reflect v1.2.x as the current stable. New
  features highlighted in the lead paragraph.
- Feature bullet list bumped from "11 widgets" to "12 widgets"
  (RSS added in v1.2.1-beta).

---

## [1.2.1] - 2026-05-26

> Two perf / stability fixes shipping on top of v1.2.0 stable. Resolves
> the long-reported "Bridge.exe at 500+ MB RAM" + "widgets lag when
> SignalRGB is sending" issues. Both root-caused to the per-frame
> rendering pipeline: a buffer-without-backpressure leak in the
> bridge, and uniform DOM mutations in the wallpaper-page paint
> regardless of whether the colour actually changed.

### Fixed — Bridge memory grew unbounded under slow wallpaper clients

`Broadcaster.broadcast_frame` called `writer.write(frame)` for every
connected client every frame without any backpressure check. Asyncio's
`StreamWriter` accepts the bytes into its output buffer regardless of
whether the underlying socket has drained, so a wallpaper page that
reads frames slowly (heavy widget tick, GPU-bound paint) lets the
bridge-side buffer grow indefinitely. Observed in v1.1 / early v1.2
testing as Bridge.exe holding 500+ MB resident.

v1.2.1 adds a per-client check: if
`transport.get_write_buffer_size() > 256 KiB` (~5 full-grid 32×32
frames at the typical 60 fps cadence) the frame is dropped for that
client. SignalRGB sends a fresh frame every ~16 ms anyway, so a
dropped frame costs at most one render. Pre-v1.2.1 the buffer would
just keep growing.

### Fixed — Widget lag when SignalRGB sends frames

The wallpaper page wrote `zoneEls[i].style.background = ...` for
every zone on every UDP frame. At a 32×32 grid (1024 zones) × 60
fps that's 61 440 DOM-style mutations per second — enough to
saturate the JS main thread and starve the 1 s widget tick
`setInterval`. Even when SignalRGB effects produced smooth
gradients where most zones were stable.

v1.2.1 caches the last-rendered RGB per zone packed into an
`Int32Array` and skips the style write when the colour hasn't
changed. For typical SignalRGB content (pulses, gradients, slow
breathing) the effective DOM-write rate drops by 70–95%. The cache
resets when `ensureZones` rebuilds the grid (count / aspect-ratio
change in the plugin's Settings).

---

## [1.2.0] - 2026-05-26

> Third stable release. Graduates the v1.2.x-beta line (17 betas
> across 2026-05-24..26) into a single shipped version. The headline
> feature is the Builder's Monitor-Setup workflow — declaring how
> bridge-reported screens map to physical monitors so the per-tile
> edit + composite-apply pipeline can handle real-world span setups
> (ultrawide-as-two-monitors, landscape+portrait pairs, etc.).
>
> Everything below is *what changed since v1.1.0 stable*; the
> intermediate `1.2.0-beta` … `1.2.17-beta` entries stay in this
> file for forensic detail but the user-visible highlights are
> grouped here.

### Configurator

- Live-preview iframe shows exactly how the current settings render
  (real widgets, real ambient, real bg) scaled into a small preview
  panel. Preview-mode flag on the wallpaper page disables
  parallax3d / pixelfx / audio listener inside the iframe so it
  doesn't fight the real instance.
- Quick Looks: seven pre-built bundles (Cyberpunk Streamer, Minimal
  Productivity, Gaming, Music Studio, Holiday Vibes, News Desk,
  Focus Mode, Stream Overlay, Pomodoro, Minimal Calendar). Apply is
  atomic via `quick-look-apply`; doesn't touch the background;
  auto-snapshots current state to preset slot 1 so a wrong pick is
  one click away from revert.
- Left section-nav rail with icon buttons + hover-expand labels.
- Per-tab "Screen settings" gear replaces the single shared trigger
  popover. Hosts the Mirror picker, Monitor-Setup picker, and
  Reset-this-screen button.
- Monitor-Setup visual picker (single / 2 H span / 2 V span) +
  per-monitor portrait/landscape rotation buttons.
- New System section migrates the tray's old "Advanced" submenu
  toggles (preset hotkeys, fullscreen pause, update check / betas,
  reload config / wallpapers, re-import bundles) into the
  Configurator. Tray becomes a thin launcher.
- Mobile / tablet stylesheet (`@media (max-width: 720px)`).

### Builder

- Simple / Advanced mode toggle. Simple is the default; hides
  brush tools, merge workflow, and history list while keeping
  Undo / Redo visible.
- Monitor Wall is the entry-point. Each declared sub-tile is its
  own slot — click to load a file (or library, or current
  background, or current canvas), drops straight into in-place
  editing. Right-click for the full menu.
- Per-tile orientation chips (▭ landscape / ▯ portrait); portrait
  tiles get a 90° CW rotation at composite-apply time.
- "Apply Wall to screens" composites one PNG per bridge screen,
  cover-fitting each tile into its declared sub-slot. Handles
  non-rectangular spans correctly (landscape + portrait monitor
  pair).
- Pick-colour-from-reference-image modal in the click-pixel tool.
- Ctrl+Shift+A hotkey for Auto-Cut from any tool context.
- Auto-Cut nudge on first image load (3× pulse on the AI button).
- Keyboard nav on wall tiles (Tab + Enter/Space + Delete).

### Wallpaper page

- New widgets: RSS feed reader (RSS 2.0 + Atom). Plus all
  pre-existing widgets gain optional header bars + tile shells.
- Animated background support — MP4 / WebM / MOV / M4V routed
  through a `<video>` element, GIF / image extensions still on
  the old image-div path.
- Bridge-offline standby card with scan-line + pulse animation,
  fades in after >5 s without a live WS so users know the bridge
  process needs starting.
- WebSocket reconnect with exponential backoff (1.5 s → 30 s cap).
- Widget-body refactor — per-widget layouts moved off the
  `.widget-X` root onto `.widget-X .widget-body` so the optional
  header strip doesn't get pulled into per-widget flex layouts.

### Bridge

- Per-screen `monitorSetup` field in `bridge.config["screens"][N]`,
  edited from the Configurator screen popover, read by the Builder
  via `/config` poll. Sanitiser validates incoming payloads.
- `quick-look-apply` + `widgets-set` WS commands for atomic widget
  array replacement under one `_mutate_screen` call.
- Magic-byte sniff on `/screen/N/background` POSTs.
- Stale `bgImage` paths dropped on `load_config`; runtime 404 on
  the `/image` proxy self-heals by POSTing `bgImage: ""` back.
- Per-screen widget ID counter (`_widgetIdSeq`) replaces the
  ms-stamp + count IDs that could collide on rapid Quick Looks.
- Cycle scheduler's `lastApplyMs` re-arms on every manual
  background upload so the cycle doesn't immediately roll back the
  user's custom background.
- Tray Advanced submenu shrinks to per-screen quick-add-widget +
  quick-effects; the rest lives in the Configurator's System
  section. Adds an "Export diagnostics bundle…" entry (config +
  library + summary metadata + reimport log as a single ZIP on
  the Desktop, OneDrive-aware path).

### Installer

- MSIX-Lively support — `msix-lively-loopback-exempt.ps1` grants
  `CheckNetIsolation LoopbackExempt` so the AppContainer-sandboxed
  WebView2 can reach `ws://127.0.0.1:17320/`. Also fixes the
  install path detection wildcard (Store-prefixed package names).

### Compatibility notes

- Configs from v1.1.x auto-migrate via `setdefault` for every new
  `DEFAULT_SCREEN_SETTINGS` key (monitorSetup, _widgetIdSeq, etc).
- Pre-v1.2.5 wall-positions localStorage keys keep working.
- v1.2.5-1.2.7 left behind `signalrgb.builder.monitor_setup`
  localStorage and `signalrgb.builder.wall_screen_count`; both
  wiped on first launch of v1.2.0 stable.

### Beta cycle for forensic detail

The 17-beta journey, with each beta's notable changes, follows
this section: [1.2.0-beta] … [1.2.17-beta]. Public release notes
should just point at this stable entry.

---

### v1.2.x beta cycle (2026-05-24 → 2026-05-26)

Eighteen betas consolidated into the v1.2.0 stable above; one
hotfix release tagged v1.2.1 stable. One-line index — `git show
<tag>` for the per-beta detail:

- **v1.2.17-beta** — hotfix: `quick-look-apply` was being silently
  dropped at the WS whitelist
- **v1.2.16-beta** — atomic Quick Look apply (snapshot, settings,
  widget-replace in one mutate); stale bgImage 404 self-heal
- **v1.2.15-beta** — diagnostics export landed in OneDrive shadow
  folder, now opens Explorer with the ZIP pre-selected
- **v1.2.14-beta** — audit round 2: WS reconnect backoff, keyboard
  nav on Wall tiles, cycle-vs-manual-upload cooldown, auto-snapshot
  before Quick Looks, Ctrl+Shift+A Auto-Cut hotkey, mobile CSS,
  diagnostics export, three new bundles, reference-image picker
- **v1.2.13-beta** — audit sweep: 14 fixes / dead-code removal /
  robustness (`_widgetIdSeq`, cover-fit applyWall, RSS URL
  allowlist, bgImage load-time existence check, magic-byte sniff
  on `/screen/N/background`, monitorSetup mirror exemption)
- **v1.2.12-beta** — Quick Looks no longer touch the background;
  Gaming bundle meters moved off the off-screen `x=1700` anchor
- **v1.2.11-beta** — Undo / Redo visible in Builder Simple mode
- **v1.2.10-beta** — `/config` exposes `monitorSetup`; tile click
  opens the action menu; per-tab gear replaces the shared trigger
- **v1.2.9-beta** — visual layout picker in the screen popover;
  faster Builder sync to Configurator (3 s poll + tab-focus refresh)
- **v1.2.8-beta** — `monitorSetup` moves into bridge config (single
  source of truth shared between Configurator + Builder);
  target-dim edit canvas; current-bg load action
- **v1.2.7-beta** — Builder Monitor-Setup cleanup: fix stuck
  portrait flag, rename Bridge → Screen, drop dead "Bildschirme"
  picker + "Canvas spannen" button
- **v1.2.6-beta** — Builder polish: per-tile orientation toggle,
  Apply preserves slots, better Apply toast
- **v1.2.5-beta** — Builder Monitor-Setup: declare spans, edit per
  tile, composite-apply with portrait rotation
- **v1.2.4-beta** — Wall tile per-slot Edit action; monitors
  override picker
- **v1.2.3-beta** — Builder Simple / Advanced toggle; Auto-Cut
  nudge on first image load; two new Quick Looks bundles
- **v1.2.2-beta** — Configurator UX overhaul: sidebar nav, screen
  popover, System section, tray Advanced shrink
- **v1.2.1-beta** — widget-body layout refactor; MSIX-Lively
  loopback exemption; RSS widget; bridge-offline standby card
- **v1.2.0-beta** — live preview iframe; first Quick Looks bundles;
  video background support; MSIX-Lively wildcard fix

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

> Pre-v1.0 betas are archived in
> [docs/CHANGELOG-archive.md](docs/CHANGELOG-archive.md) for forensic
> detail.
