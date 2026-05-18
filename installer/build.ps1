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

# --- 1. Generate icon + thumbnail --------------------------------------------
Write-Host "[1/5] Generating icon.ico + thumbnail.png" -ForegroundColor Yellow
& python (Join-Path $installer "generate_icon.py")
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }
& python (Join-Path $installer "generate_thumbnail.py")
if ($LASTEXITCODE -ne 0) { throw "thumbnail generation failed" }

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
        --add-data "builder.html;." `
        --distpath dist_bridge --workpath build_bridge `
        bridge.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
} finally {
    Pop-Location
}

# --- 3. Rebuild the 3 Lively zips --------------------------------------------
Write-Host "[3/5] Rebuilding Lively wallpaper zips" -ForegroundColor Yellow
$src   = Join-Path $bridgeDir "wallpaper"
$stage = Join-Path $bridgeDir "dist_stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null
foreach ($n in 0, 1, 2) {
    $label = ($n + 1).ToString()
    $st = Join-Path $stage ("stage_screen{0}" -f $n)
    Copy-Item -Path $src -Destination $st -Recurse
    $idx  = Join-Path $st "index.html"
    $info = Join-Path $st "LivelyInfo.json"
    (Get-Content $idx  -Raw) -replace '(<meta name="signalrgb-screen-index" content=")\d+(">)', ('${1}' + $n + '${2}') | Set-Content $idx  -NoNewline
    (Get-Content $info -Raw) -replace '__SCREEN_LABEL__', $label | Set-Content $info -NoNewline
    $zip = Join-Path $bridgeDir ("SignalRGB_Glow_Screen{0}.zip" -f $label)
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $st "*") -DestinationPath $zip -CompressionLevel Optimal
}
Remove-Item $stage -Recurse -Force

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
