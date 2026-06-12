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

## Bundled wallpaper library (`installer/assets/library/`)

The 38 cyberpunk / synthwave / aurora / underwater / sci-fi wallpapers
shipped under `installer/assets/library/` are generated locally with
**Juggernaut XL v9 (RunDiffusion Photo v2 variant)** — a photorealistic
fine-tune of **Stable Diffusion XL Base 1.0** (Stability AI). Both are
released under **CreativeML Open RAIL++-M**. Per Section IV/V of that
licence:

> *"… you bear sole liability for any use of the Model and you agree
> not to use the Model for the use cases listed in Section II … The
> License is not intended to restrict you from using the Output …"*

The licence covers the *model weights*; Output is **not** subject to
the licence as long as it is not produced for the prohibited use
cases (defamation, illegal content, etc.) listed in Section II. None
of our prompts touch those categories — they generate landscape /
abstract / cityscape backgrounds — so the bundled WebPs ship
unencumbered under our MIT umbrella.

- **SDXL Base 1.0** weights — CreativeML Open RAIL++-M.
  <https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0>
- **Model: Juggernaut XL** (v9 RunDiffusion Photo v2) by **KandooAI**
  — fine-tune of SDXL Base 1.0, released under CreativeML Open
  RAIL++-M with an addendum (linked below). Per the addendum,
  Section III: *"Licensor claims no rights in the Output you
  generate"* — we ship the generated WebPs unencumbered under
  this project's MIT umbrella. The addendum requires creator
  attribution (this block), which we satisfy here.
  - Model: <https://civitai.com/models/133005/juggernaut-xl>
  - License addendum: <https://civitai.com/models/license/1759168>
- **Upscaler: 4xNomos8kDAT** by **Philip Hofmann (Phips)** —
  CC-BY-4.0. Used to take each Juggernaut 1024-grade output up to
  3840×2160 cleanly. Attribution required by the licence: this
  block satisfies it. Earlier wave-1 packs used 4x-UltraSharp; we
  replaced that with 4xNomos8kDAT because UltraSharp is
  CC-BY-NC-SA 4.0 (non-commercial) which would have tainted the
  MIT redistribution chain.
  - <https://huggingface.co/Phips/4xNomos8kDAT>
- Generation script (in-tree, ComfyUI batch): not committed because
  the ComfyUI workflow lives outside the repo. Provenance for every
  shipped image is documented in
  [`installer/assets/library/IMAGES_NOTICE.md`](../installer/assets/library/IMAGES_NOTICE.md)
  alongside the bundled assets.
- Post-processing (in-tree): `tools/import_repo_clean.py` ingests
  the ComfyUI batch (3840×2160 RGBA with luminance-alpha already
  baked in), then emits three WebP variants per slug:
  `<slug>.webp` (1920×1080), `<slug>.thumb.webp` (320×180), and
  `<slug>.4k.webp` (3840×2160). The Configurator picks the right
  one based on each screen's reported viewport size at apply
  time.

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

## Builder Auto-cut algorithms (in-tree, no external deps)

v0.9.20+ replaced the lazy-loaded ONNX model with pure-JavaScript
saliency detection that runs locally on the canvas. Two algorithms,
both based on public-domain mathematics:

- **Auto saliency** — frequency-tuned saliency *(Achanta, Hemami,
  Estrada, Süsstrunk 2009, "Frequency-tuned Salient Region
  Detection")*. For each pixel, compute Euclidean colour distance
  from the image's mean RGB plus a brightness-above-mean premium;
  threshold adaptively. The algorithm is published mathematics; no
  patent, no copyright on the technique itself, our implementation
  is original.
- **Otsu (brightness)** — Otsu's optimal histogram threshold *(Otsu
  1979)*. Also published mathematics, original implementation.

Neither algorithm needs a model, network, or third-party library.
Both run in tens of milliseconds on a typical canvas.

### Power-user ONNX path (opt-in, not the default)

The earlier code paths for loading an external ONNX saliency model
via `onnxruntime-web` are still in `builder.html` but hidden from
the UI by default. Users who set
`localStorage["builder.aiEnabled"] = "1"` (or supply a model URL via
`localStorage["builder.aiModelUrl"]`) get a third "Custom ONNX model"
entry in the mode dropdown. If they use it:

- `onnxruntime-web` (MIT) is fetched from jsDelivr on first use
  (~3 MB). <https://github.com/microsoft/onnxruntime>
- The model file is fetched from whichever URL the user configured.
  The licence terms of that model attach to *the user* (their
  browser is what downloads it), not to our MIT distribution.

The default UX never triggers either fetch, so no third-party
dependency is in play for normal users.

### Why we dropped the lazy-loaded default model

Earlier betas (v0.9.16 → v0.9.19) shipped a default URL pointing at
RMBG-1.4 (BRIA, non-commercial) or U²-Netp (Apache 2.0) on
Hugging Face / rembg releases. Multiple URLs proved unreliable
(some 404'd, others split the model graph from its weights and
ORT-Web couldn't auto-resolve the second file), and the BRIA
default also raised a non-commercial-licence concern. v0.9.20
walks the whole default-fetch path back to in-tree algorithms.

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
| Auto-cut algorithms (frequency-tuned saliency, Otsu) | Published mathematics, no copyright | In-tree pure-JS implementations of the Achanta-2009 and Otsu-1979 algorithms. The algorithms themselves are published academic work with no patent or copyright on the *technique*; our implementations are original code. |
| onnxruntime-web (opt-in only) | MIT | **Not bundled and not loaded by default.** Only fetched if the user explicitly enables the "Custom ONNX model" mode via `localStorage["builder.aiEnabled"]` or `["builder.aiModelUrl"]`. Permissive licence; attribution kept above for users who do opt in. |

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
