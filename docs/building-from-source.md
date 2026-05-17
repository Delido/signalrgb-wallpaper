# Building from Source

You only need this if you're modifying the bridge / plugin / wallpaper
HTML, or producing your own release artifacts. End users grab pre-built
files from the [Releases page](https://github.com/Delido/signalrgb-wallpaper/releases).

## Prerequisites

- **Windows 10/11**
- **Python 3.11+** with `pip` on PATH. Get it from
  [python.org](https://www.python.org/downloads/) or
  `winget install Python.Python.3.13`.
- **PowerShell 7** (for the packaging snippets). The Windows-built-in
  PowerShell 5.1 also works for most commands but `Compress-Archive` is
  finicky on older builds.
- *Optional:* the [GitHub CLI](https://cli.github.com/)
  (`winget install GitHub.cli`) if you plan to push releases.

## Initial setup

```powershell
git clone https://github.com/Delido/signalrgb-wallpaper.git
cd signalrgb-wallpaper

# Install Python deps for the bridge + tray
python -m pip install --user pystray Pillow pyinstaller
```

That's it for deps. The bridge uses only stdlib + pystray + Pillow +
tkinter (bundled with Python on Windows).

## Building `SignalRGBBridge.exe`

```powershell
cd wallpaper_bridge

python -m PyInstaller `
  --onefile `
  --noconsole `
  --name SignalRGBBridge `
  --hidden-import pystray._win32 `
  --collect-all pystray `
  --collect-submodules PIL `
  --add-data "builder.html;." `
  --distpath dist_bridge `
  --workpath build_bridge `
  bridge.py

# Output: wallpaper_bridge\dist_bridge\SignalRGBBridge.exe  (~19 MB)
```

Flags explained:

- `--onefile` — single self-contained exe; users don't need Python.
- `--noconsole` — no console window when launched (we're a tray app).
  To debug, temporarily drop this flag and rebuild — stdout will be
  visible in cmd.
- `--hidden-import pystray._win32` + `--collect-all pystray` — PyInstaller's
  static analyser misses pystray's Win32 backend; this forces inclusion.
- `--collect-submodules PIL` — Pillow's image loaders are lazy-loaded;
  this pulls them all in so the tray icon image works.
- `--add-data "builder.html;."` — bundles the in-browser wallpaper
  builder so it's served at `/builder`. Path is resolved relative to
  the spec file's directory (CWD), so don't pass `--specpath` or the
  source path won't resolve.

### Quick rebuild loop during development

When iterating on `bridge.py`, save the time of the full rebuild by
running the Python source directly:

```powershell
cd wallpaper_bridge
python bridge.py
```

You get a real console with stdout — ideal for debugging. The tray
icon, settings dialog, WS server etc. all work identically.

## Building the 3 Lively wallpaper zips

The `wallpaper_bridge/wallpaper/` folder is a *template*. We generate
3 per-screen zips by patching the `<meta>` screen-index and
`LivelyInfo.json` title:

```powershell
$root = "$PWD"   # run from repo root
$src  = Join-Path $root "wallpaper_bridge\wallpaper"
$out  = Join-Path $root "wallpaper_bridge\dist_stage"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Path $out | Out-Null

foreach ($n in 0, 1, 2) {
    $label = ($n + 1).ToString()
    $stage = Join-Path $out ("stage_screen{0}" -f $n)
    Copy-Item -Path $src -Destination $stage -Recurse

    $idx  = Join-Path $stage "index.html"
    $info = Join-Path $stage "LivelyInfo.json"
    (Get-Content $idx  -Raw) -replace `
        '(<meta name="signalrgb-screen-index" content=")\d+(">)', `
        ('${1}' + $n + '${2}') | Set-Content $idx  -NoNewline
    (Get-Content $info -Raw) -replace '__SCREEN_LABEL__', $label | `
        Set-Content $info -NoNewline

    $zip = Join-Path $root ("wallpaper_bridge\SignalRGB_Glow_Screen{0}.zip" -f $label)
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal
}

Remove-Item $out -Recurse -Force
```

Output: `wallpaper_bridge\SignalRGB_Glow_Screen1.zip`,
`Screen2.zip`, `Screen3.zip` (~12 KB each).

## Smoke-testing the bridge

`wallpaper_bridge/smoke_test.py` opens two WS subscribers (`?screen=0`
and `?screen=1`) and verifies that a fake UDP datagram tagged for one
screen reaches only that screen's clients.

```powershell
# Start the bridge first
.\wallpaper_bridge\dist_bridge\SignalRGBBridge.exe
# In another shell
python .\wallpaper_bridge\smoke_test.py
```

> The smoke test will misreport `FAIL` if SignalRGB is actively
> streaming frames through the bridge at the same time (its WS clients
> pick up real plugin traffic mixed with the test payload). Stop
> SignalRGB or unpair the plugin before running it.

## Publishing a release (maintainer notes)

1. Bump the `Version()` export in `SignalRGB_Desktop_Wallpaper.js` and
   add an entry to `CHANGELOG.md`.
2. Rebuild `SignalRGBBridge.exe` and the 3 zips (commands above).
3. Commit, tag, push:

   ```powershell
   git add -A
   git commit -m "Release vX.Y.Z"
   git tag vX.Y.Z
   git push origin main --tags
   ```

4. Create the release with artifacts:

   ```powershell
   gh release create vX.Y.Z `
     --title "vX.Y.Z" `
     --notes-file CHANGELOG.md `
     wallpaper_bridge\dist_bridge\SignalRGBBridge.exe `
     wallpaper_bridge\SignalRGB_Glow_Screen1.zip `
     wallpaper_bridge\SignalRGB_Glow_Screen2.zip `
     wallpaper_bridge\SignalRGB_Glow_Screen3.zip `
     SignalRGB_Desktop_Wallpaper.js `
     SignalRGB_Desktop_Wallpaper.qml
   ```

5. Verify on the [Releases page](https://github.com/Delido/signalrgb-wallpaper/releases).
