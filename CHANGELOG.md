# Changelog

All notable changes to **SignalRGB Desktop Wallpaper** are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
