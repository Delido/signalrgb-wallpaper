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
- **Quotable** — random-quote API behind the *Quote* widget. Data is
  CC BY-SA; the widget footer says *"via Quotable"*.
  <https://github.com/lukePeavey/quotable>
- **GitHub Releases API** — polled at startup + every 24 h by the in-app
  update checker.
  <https://docs.github.com/en/rest/releases/releases>

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
