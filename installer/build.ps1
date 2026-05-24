# One-shot installer build.
#
# Re-generates the icon, rebuilds SignalRGBBridge.exe via PyInstaller,
# rebuilds the 3 per-screen Lively zips, then compiles the Inno Setup
# installer.  Output:
#   installer_out\SignalRGBWallpaperSetup-<version>.exe
#
# Run from anywhere in the repo:
#   pwsh installer\build.ps1                  # uses version from bridge.py
#   pwsh installer\build.ps1 -Version 0.4.0   # explicit override

[CmdletBinding()]
param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"

$repoRoot   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$bridgeDir  = Join-Path $repoRoot "wallpaper_bridge"
$installer  = Join-Path $repoRoot "installer"
$outDir     = Join-Path $repoRoot "installer_out"

if (-not $Version) {
    # Extract APP_VERSION = "X.Y.Z" from bridge.py so the installer
    # filename always matches the binary.
    $pyContent = Get-Content (Join-Path $bridgeDir "bridge.py") -Raw
    if ($pyContent -match 'APP_VERSION\s*=\s*"([^"]+)"') {
        $Version = $Matches[1]
    } else {
        throw "Cannot find APP_VERSION in bridge.py — pass -Version explicitly"
    }
}
Write-Host "Building installer for v$Version" -ForegroundColor Cyan

# --- 1. Generate icon + thumbnail + README banner + Workshop preview ---------
Write-Host "[1/5] Generating icon.ico + thumbnail.png + banner.png + workshop_preview.png" -ForegroundColor Yellow
& python (Join-Path $installer "generate_icon.py")
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }
& python (Join-Path $installer "generate_thumbnail.py")
if ($LASTEXITCODE -ne 0) { throw "thumbnail generation failed" }
& python (Join-Path $installer "generate_banner.py")
if ($LASTEXITCODE -ne 0) { throw "banner generation failed" }
& python (Join-Path $installer "generate_workshop_preview.py")
if ($LASTEXITCODE -ne 0) { throw "workshop preview generation failed" }
& python (Join-Path $installer "generate_library.py")
if ($LASTEXITCODE -ne 0) { throw "library generation failed" }

# --- 2. Rebuild SignalRGBBridge.exe ------------------------------------------
Write-Host "[2/5] Rebuilding SignalRGBBridge.exe" -ForegroundColor Yellow
Push-Location $bridgeDir
try {
    Remove-Item "build_bridge", "dist_bridge", "*.spec" -Recurse -Force -ErrorAction SilentlyContinue
    & python -m PyInstaller `
        --onefile --noconsole `
        --name SignalRGBBridge `
        --hidden-import pystray._win32 `
        --collect-all pystray `
        --collect-submodules PIL `
        --collect-all psutil `
        --collect-all winrt `
        --add-data "builder.html;." `
        --add-data "configurator.html;." `
        --add-data "help.html;." `
        --add-data "wallpaper;wallpaper" `
        --distpath dist_bridge --workpath build_bridge `
        bridge.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
} finally {
    Pop-Location
}

# --- 3. Stage Lively wallpapers (folders + zips) -----------------------------
# We need two formats:
#   • Folders under  wallpaper_bridge\lively_bundles\signalrgb-glow-screen-N\
#     — fed straight into Lively's Library by the installer when the
#     "Auto-import into Lively" task is checked, deterministic folder
#     names so re-installs / updates overwrite in place.
#   • Zips         wallpaper_bridge\SignalRGB_Glow_ScreenN.zip
#     — kept for the GitHub release page (manual-import users) and as a
#     fallback when the installer's auto-import is unchecked.
Write-Host "[3/5] Staging Lively wallpaper folders + zips" -ForegroundColor Yellow
$src      = Join-Path $bridgeDir "wallpaper"
$livStage = Join-Path $bridgeDir "lively_bundles"
if (Test-Path $livStage) { Remove-Item $livStage -Recurse -Force }
New-Item -ItemType Directory -Path $livStage | Out-Null
foreach ($n in 0, 1, 2, 3) {
    $label = ($n + 1).ToString()
    $bundleDir = Join-Path $livStage ("signalrgb-glow-screen-{0}" -f $label)
    Copy-Item -Path $src -Destination $bundleDir -Recurse
    $idx  = Join-Path $bundleDir "index.html"
    $info = Join-Path $bundleDir "LivelyInfo.json"
    (Get-Content $idx  -Raw) -replace '(<meta name="signalrgb-screen-index" content=")\d+(">)', ('${1}' + $n + '${2}') | Set-Content $idx  -NoNewline
    (Get-Content $info -Raw) -replace '__SCREEN_LABEL__', $label | Set-Content $info -NoNewline
    # Lively bundles use thumbnail.png as the tile preview — the
    # 1920×1080 Workshop preview is dead weight here.
    Remove-Item (Join-Path $bundleDir "workshop_preview.png") -Force -ErrorAction SilentlyContinue
    $zip = Join-Path $bridgeDir ("SignalRGB_Glow_Screen{0}.zip" -f $label)
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $bundleDir "*") -DestinationPath $zip -CompressionLevel Optimal
}

# --- 3a. Single combined Wallpaper Engine bundle for Workshop ----------------
# One project that the subscriber can assign to all N monitors, choosing a
# different "screenIndex" property per assignment. The page's `<meta
# signalrgb-screen-index>` tag isn't pinned here — Wallpaper Engine
# delivers the screenIndex via wallpaperPropertyListener and the page
# reconnects the WS to the matching ?screen=N route.
Write-Host "[3a/5] Staging single combined Wallpaper Engine bundle" -ForegroundColor Yellow
$weSingle = Join-Path $bridgeDir "we_bundles_single\signalrgb-glow"
if (Test-Path $weSingle) { Remove-Item $weSingle -Recurse -Force }
New-Item -ItemType Directory -Path $weSingle | Out-Null
Copy-Item -Path (Join-Path $src "*") -Destination $weSingle -Recurse
# Lively-only files are noise in a WE bundle
Remove-Item (Join-Path $weSingle "LivelyInfo.json") -Force -ErrorAction SilentlyContinue
# Reset the screen-index meta tag to 0 — WE will override it via the
# screenIndex property below, but a non-WE preview should still load.
$idx = Join-Path $weSingle "index.html"
(Get-Content $idx -Raw) -replace '(<meta name="signalrgb-screen-index" content=")\d+(">)', '${1}0${2}' |
    Set-Content $idx -NoNewline
$singleDesc = @"
[b]Live SignalRGB-driven glow on your desktop wallpaper.[/b]

This wallpaper renders the colours of your currently running SignalRGB effect through transparent regions of a background image. Perfect for setups that already have SignalRGB driving fan / keyboard / strip lighting — your wallpaper now matches.

[b]Important — requires the SignalRGB Wallpaper Bridge:[/b]
[list]
[*] Download + install from [url=https://github.com/Delido/signalrgb-wallpaper/releases]github.com/Delido/signalrgb-wallpaper[/url]
[*] The installer copies a SignalRGB plugin into your WhirlwindFX/Plugins folder and registers a local bridge (UDP 17320 + WebSocket).
[*] Once the bridge is running, the wallpaper picks up the live colours automatically. No bridge running = the wallpaper shows just the background image (no glow).
[/list]

[b]Multi-monitor:[/b] assign this wallpaper to every monitor you want to drive (up to 4), and pick a different [b]Screen index[/b] in WE's properties panel per assignment. The bridge routes the matching SignalRGB device's colours to each screen automatically.

[b]Features driven by the bridge:[/b]
[list]
[*] In-browser configurator + builder with drag-and-resize widget layout — clock, calendar, weather, sticky notes, countdown, picture frame, quote, CPU / RAM / GPU / hardware sensor meters, audio spectrum, Now-playing (Windows SMTC)
[*] [b]Twelve ambient effects:[/b] snow, rain, sparks, aurora, constellation, fireflies, plasma, vortex, bubbles, matrix, starfield, lightning — optionally tinted from the live glow colour
[*] Whole-screen audio-reactive glow layer (pulse / spectrum / waveform)
[*] Cursor pixelfx (mouse trail, hover glow, click ripple) and 3D parallax on the background
[*] In-browser Builder with one-click Auto-cut (Otsu + saliency, no AI download), monitor-wall workflow, brush tools, pattern fills
[*] Preset slots, wallpaper auto-cycle, global preset hotkeys, per-app/game profiles
[*] DE / EN UI, auto-detected from your Windows locale
[*] Auto-pause when a fullscreen app is foreground
[/list]

MIT licensed. Open source: [url=https://github.com/Delido/signalrgb-wallpaper]github.com/Delido/signalrgb-wallpaper[/url]
"@
# Wallpaper Engine's `combo` property delivers `value` as a string, so the
# page's setScreenIndex() parses it back into an int. Four entries cover
# the bridge's MAX_SCREENS = 4.
$singleProject = @{
    title       = "SignalRGB Glow"
    description = $singleDesc
    type        = "Web"
    file        = "index.html"
    preview     = "workshop_preview.png"
    tags        = @("RGB","Customizable","Web","Abstract","Multi-Monitor")
    contentrating = "Everyone"
    version     = 8
    general     = @{
        # WE ignores wallpaperRegisterAudioListener() callbacks unless
        # this flag is set INSIDE the `general` block (not at the top
        # level). Without it the audio-glow layer + audio-spectrum
        # widget never see any FFT samples on WE.
        supportsaudioprocessing = $true
        properties = @{
            screenIndex = @{
                order   = 0
                text    = "Screen index (sets which SignalRGB Desktop Wallpaper device drives this monitor)"
                type    = "combo"
                value   = "0"
                options = @(
                    @{ label = "Screen 1"; value = "0" },
                    @{ label = "Screen 2"; value = "1" },
                    @{ label = "Screen 3"; value = "2" },
                    @{ label = "Screen 4"; value = "3" }
                )
            }
        }
    }
} | ConvertTo-Json -Depth 6
Set-Content -Path (Join-Path $weSingle "project.json") -Value $singleProject -Encoding UTF8
# Maintainer note: end users don't care, but for the project owner —
# this project.json has NO `workshopid` / `workshopurl` fields, so
# whenever the Inno installer copies it over WE's myprojects copy,
# the existing workshopid linkage is destroyed. WE's next "Share on
# Workshop" submit then creates a NEW Steam Workshop item instead of
# updating the existing one. Run `installer\maintainer-restore-workshopid.ps1`
# after each install to put the workshopid back before opening WE.

# --- 3b. (retired in 0.7.2-beta) ----------------------------------------------
# We used to stage four per-screen WE bundles here so each monitor got its
# own Library tile. The single combined bundle from step 3a covers the same
# use case via the screenIndex property (assigned N times with a different
# index per assignment), so the installer + Workshop pipeline now ship only
# the single bundle. Drop the legacy folder if a previous build left it
# behind so the installer can't accidentally pull stale per-screen sources.
$legacyWeStage = Join-Path $bridgeDir "we_bundles"
if (Test-Path $legacyWeStage) { Remove-Item $legacyWeStage -Recurse -Force }

# --- 4. Package the pause-tester diagnostic wallpaper -------------------------
Write-Host "[4/5] Packaging Lively pause-tester" -ForegroundColor Yellow
$testerSrc = Join-Path $repoRoot "tools\lively-pause-tester"
$testerZip = Join-Path $bridgeDir "SignalRGB_LivelyPauseTester.zip"
if (Test-Path $testerSrc) {
    if (Test-Path $testerZip) { Remove-Item $testerZip -Force }
    Compress-Archive -Path (Join-Path $testerSrc "*") -DestinationPath $testerZip -CompressionLevel Optimal
} else {
    Write-Host "  (tools\lively-pause-tester missing — skipping)" -ForegroundColor DarkGray
}

# --- 5. Compile Inno Setup ----------------------------------------------------
Write-Host "[5/5] Compiling installer" -ForegroundColor Yellow
$isccCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    throw "ISCC.exe not found. Install Inno Setup 6: winget install JRSoftware.InnoSetup"
}
Write-Host "  ISCC: $iscc"
& $iscc "/Q" "/DMyAppVersion=$Version" (Join-Path $installer "signalrgb-wallpaper.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC compile failed" }

$out = Join-Path $outDir ("SignalRGBWallpaperSetup-{0}.exe" -f $Version)
if (Test-Path $out) {
    $sz = (Get-Item $out).Length
    Write-Host ("[OK] {0}  ({1:N0} bytes)" -f $out, $sz) -ForegroundColor Green
} else {
    throw "Expected output not found: $out"
}
