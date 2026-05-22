# Open-source credits

This project couldn't exist without the work that came before it. The full
list of every dependency, transitive runtime, public API, and the licence
under which each ships is below.

## Bundled in `SignalRGBBridge.exe`

- **Python 3** — PSF License.
  <https://www.python.org/> · <https://docs.python.org/3/license.html>
- **Python stdlib at runtime**: `asyncio`, HTTP-server building blocks,
  `hashlib`, `base64`, `struct`, `urllib`, `json`, `mimetypes`, `threading`,
  `webbrowser`, `tkinter` (Settings + About dialogs) — all PSF License.
- **pystray** (system tray icon) — LGPL 3.0.
  <https://github.com/moses-palmer/pystray>
- **Pillow / PIL** (image library, tray-icon rendering, About-dialog avatar)
  — MIT-CMU (HPND).
  <https://github.com/python-pillow/Pillow>
- **psutil** (cross-platform process / system stats) — BSD-3-Clause. Used by
  the SysStats poller behind the CPU / RAM widgets.
  <https://github.com/giampaolo/psutil>
- **winrt-Windows.Media.Control** (Now-playing widget data source) — MIT.
  Microsoft's split-package WinRT projection for Python; replaces the legacy
  `winsdk` and feeds the SMTC snapshot (title / artist / progress) into the
  1 Hz sysstats push the wallpaper consumes.
  <https://github.com/pywinrt/python-winsdk>
- **PyInstaller** (single-file packager — used at build time, the bootloader
  stub it embeds ships in this exe) — GPL 2.0+ with linking exception
  (commercial / closed-source apps OK).
  <https://github.com/pyinstaller/pyinstaller>
- **`builder.html`** (the in-browser wallpaper editor served at `/builder`)
  — vanilla HTML5 / CSS / JS. No third-party JS or CSS frameworks. Uses
  only native browser APIs (Canvas, FileReader, Fetch, Blob,
  URL.createObjectURL). System fonts (Segoe UI, Roboto, ui-sans-serif,
  Consolas) are requested via CSS font-family fallback chains, not bundled.
- **`configurator.html`** (the in-browser configurator served at
  `/configurator`) — also vanilla HTML5 / CSS / JS.

## Bundled in each Lively / Wallpaper Engine wallpaper

- **interact.js** (drag + resize for placeable widgets) — MIT. The full
  licence text ships next to `interact.min.js` in every Lively zip and WE
  bundle as `interact.LICENSE.txt`.
  <https://github.com/taye/interact.js>

## Web services queried at runtime (not bundled)

- **Open-Meteo** — free weather API. Data is CC-BY 4.0; the widget shows an
  *"via Open-Meteo"* attribution in its footer whenever it has real data.
  <https://open-meteo.com/>
  Note: every weather API call is made by the wallpaper page running in
  the end-user's CEF / WebView. This project does not centrally proxy or
  re-host the data; Open-Meteo sees many independent low-volume callers,
  one per user, well inside their free non-commercial tier.
- **Quote pool — local, bundled.** The *Quote* widget previously hit
  `api.quotable.io`, but the service went dark in early 2026. v0.9.x
  replaced the live fetch with a 50-entry pool of public-domain /
  unattributed quotations baked into `wallpaper/index.html`. No
  external network call, no third-party data dependency, no
  attribution requirement.
- **GitHub Releases API** — polled at startup + every 24 h by the in-app
  update checker.
  <https://docs.github.com/en/rest/releases/releases>
- **LibreHardwareMonitor** — Mozilla Public License 2.0. Optional;
  drives the *Hardware Sensor* widget family (CPU / GPU temps, fan
  RPMs, voltages, drive temps, power). When the user has LHM running
  with its *Remote Web Server* enabled (Options → Remote Web Server),
  our bridge polls `http://localhost:8085/data.json` once per second
  and pushes the flattened sensor tree to the wallpaper page alongside
  the existing CPU / RAM stats. **We do not bundle LHM** — it has to
  be installed separately by the user, so its MPL terms don't
  propagate to our MIT distribution. <https://github.com/LibreHardwareMonitor/LibreHardwareMonitor>

## Lazy-loaded in the browser (Builder Auto-cut, not bundled)

The Builder's *Auto-cut → AI saliency* mode (v0.9.16+) fetches its
runtime + model on first click. Nothing is bundled with our installer
or our wallpaper zips; each user's browser fetches these directly
from the upstream when they choose to use the feature.

- **onnxruntime-web** — MIT. Microsoft's ONNX inference runtime for
  the web (WebAssembly + optional WebGPU backends). We pull
  `ort.min.js` + the matching `.wasm` files from jsDelivr's
  npm mirror on first AI-mode click. About 3 MB total, browser-cached
  after. <https://github.com/microsoft/onnxruntime>
- **U²-Netp (saliency model)** — Apache License 2.0. *"U²-Net:
  Going Deeper with Nested U-Structure for Salient Object
  Detection"* by Qin et al. The "p" variant is the small / fast
  version (~4 MB, 320×320 input). v0.9.18 made this the default
  AI-mode model — Apache 2.0 is permissive and explicitly allows
  commercial use, so the AI cut-out feature is now free for any
  user regardless of whether their wallpaper setup is private or
  commercial. The model file is fetched from Hugging Face by the
  user's browser on first click; we do not bundle or redistribute
  it. <https://github.com/xuebinqin/U-2-Net>
  Earlier v0.9.16 + v0.9.17 betas pointed at *RMBG-1.4* (BRIA
  RMBG v1.4 License v1.0, **non-commercial only**); those tags
  were yanked from Releases to avoid steering commercial users
  into BRIA's licence. If a user manually overrides
  `localStorage["builder.aiModelUrl"]` to a non-permissive model,
  the licence attaches to *them* (their browser is what downloads
  the model), not to our MIT distribution.
- **CDN providers (jsDelivr, Hugging Face)** — fetch endpoints, not
  bundled assets. Both have free public access tiers our usage sits
  well inside (one fetch per user per AI cold-start).

## Hosts the wallpaper plays inside (not bundled)

- **Lively Wallpaper** — GPL 3.0. The recommended free host.
  <https://github.com/rocksdanister/lively>
- **Wallpaper Engine** (Steam) — proprietary, paid. The wallpaper page
  targets WE's Web format too; the installer can copy bundles straight into
  Steam's `wallpaper_engine\projects\myprojects` folder when detected.
  <https://www.wallpaperengine.io/>
- **SignalRGB** — proprietary; this project uses their public plugin API.
  <https://signalrgb.com/> · <https://docs.signalrgb.com/>

## Build tooling (not shipped, used only at release time)

- **GitHub CLI** (releases) · `git` · `winget` · **Inno Setup** (installer
  compilation).

## License compatibility summary

This project is **MIT licensed** (see `LICENSE` at the repo root). MIT is
maximally permissive and compatible with all dependencies below. Each item
lists the dep, its license, and the (short) reason redistribution inside an
MIT product is OK.

| Dep | License | Why we can bundle / use it |
| --- | --- | --- |
| Python 3 (runtime + stdlib) | PSF License | PSF explicitly permits redistribution including in derivative / commercial work. |
| pystray | LGPL 3.0 | LGPL allows linking from non-LGPL apps. Attribution above is the required notice; users wanting to swap pystray can replace the bundled module files inside the PyInstaller extraction. |
| Pillow / PIL | MIT-CMU (HPND) | Permissive — same shape as MIT; just include the notice (we do, here). |
| psutil | BSD-3-Clause | Permissive — include notice (here) and don't claim endorsement (we don't). |
| winrt-Windows.Media.Control | MIT | Permissive — used to read SMTC for the Now-playing widget. Just attribution. |
| PyInstaller bootloader stub | GPL 2.0+ **with bootloader linking exception** | The exception (see PyInstaller's `COPYING.txt`) explicitly allows building closed-source / commercial / non-GPL applications. Our app is MIT, well inside the carve-out. |
| interact.js | MIT | Permissive — we ship `interact.LICENSE.txt` next to the .js in every wallpaper bundle. |
| Open-Meteo data | CC-BY 4.0 | Attribution required at point of display. Done in the Weather widget footer (*"via Open-Meteo"*) and here. |
| Local quote pool (Quote widget) | Public domain / unattributed | No external service — 50 short quotations bundled in `wallpaper/index.html`. No licensing or rate-limit obligations attach. |
| GitHub Releases API | (Free public API) | Read-only, well under rate limits for unauthenticated requests, no terms we're violating. |
| LibreHardwareMonitor | Mozilla Public License 2.0 | **Not bundled.** Polled at runtime via the user's own LHM install. MPL 2.0 is file-based weak copyleft — it would only impose obligations on us if we redistributed LHM's source files (modified or not). Since we just call its HTTP server like any other client, no propagation. |
| onnxruntime-web | MIT | **Not bundled.** Fetched from jsDelivr at runtime when the user opts into Builder Auto-cut → AI mode. Permissive, attribution above. |
| U²-Netp saliency model | Apache 2.0 | **Not bundled.** Fetched from Hugging Face by the user's browser on first AI-mode click. Apache 2.0 is permissive and explicitly commercial-use-OK; attribution above (in the lazy-load section). Default since v0.9.18. |

### Hosts the wallpaper *runs inside* (we don't bundle them)

These are runtime environments our wallpaper bundles target — analogous to
"a Python script running on a GPL'd interpreter" or "a webpage rendered in
Chrome". Their license terms cover the host, not the content rendered
inside it.

- **Lively Wallpaper (GPL 3.0)** — we don't link to, modify, or bundle
  Lively. Our wallpaper is a standard HTML5 file that runs in Lively's
  WebView the same way any other community wallpaper does. No GPL
  propagation.
- **Wallpaper Engine (proprietary)** — Steam's standard Workshop content
  terms apply when uploading. We comply: the wallpaper is original code +
  permissively-licensed deps with attribution.
- **SignalRGB (proprietary)** — we use their **public plugin API**.
  SignalRGB markets a community plugin ecosystem; our plugin uses only
  documented entry points (`device.color()`, `udp.createSocket()`, etc.).

### What this means in practice

- Our distribution is MIT — anyone can fork, modify, redistribute,
  including commercially.
- The PyInstaller-built exe carries:
  - MIT for our own code (and the wallpaper bundles).
  - Permissive notices for Pillow, psutil, interact.js.
  - LGPL notice for pystray (with a documented "you can replace the
    bundled module files" path).
  - PyInstaller bootloader's GPL+exception cover (the exception kicks in
    automatically).
- No copyleft contamination of our own code.

This audit was last refreshed for **v0.9.18-beta** (2026-05-23).
