# Push a manifest update for Delido.SignalRGBWallpaper to
# microsoft/winget-pkgs via wingetcreate.
#
# Run AFTER `gh release create vX.Y.Z` has published a stable build.
# Beta tags are refused — winget is for end users, betas stay on the
# GitHub Releases page only.
#
# Usage:
#   pwsh installer\winget-publish.ps1                 # auto-detects latest stable
#   pwsh installer\winget-publish.ps1 -Version 1.2.1  # explicit override
#   pwsh installer\winget-publish.ps1 -DryRun         # build the manifest, skip PR submit
#
# Requirements:
#   • wingetcreate installed:  winget install Microsoft.WingetCreate
#   • GitHub PAT with `public_repo` scope in env var
#     WINGETCREATE_GITHUB_TOKEN  (or pass -Token).
#     The PAT submits a PR against microsoft/winget-pkgs on your
#     behalf; the upstream auto-validation pipeline picks it up
#     within a few minutes.
#
# What it does:
#   1. Resolves the version to publish (CLI arg, else latest stable git tag).
#   2. Builds the GitHub Release asset URL for the installer.
#   3. Sanity-checks the asset URL responds 200 (avoids submitting
#      a manifest for an asset that's still uploading).
#   4. Invokes  `wingetcreate update Delido.SignalRGBWallpaper`  with
#      --submit so the PR lands on microsoft/winget-pkgs.

[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$Token   = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$pkgId    = "Delido.SignalRGBWallpaper"
$ghUser   = "Delido"
$ghRepo   = "signalrgb-wallpaper"

# ── 1. Resolve version ───────────────────────────────────────────────────────
if (-not $Version) {
    Push-Location $repoRoot
    try {
        # Latest tag matching vX.Y.Z exactly (no -beta / -rc suffix).
        # `git tag --sort=-v:refname` orders by semver-ish desc.
        $tags = & git tag --list "v*" --sort=-v:refname 2>$null
        $stable = $tags | Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } | Select-Object -First 1
        if (-not $stable) { throw "Could not find a stable vX.Y.Z tag in git tag --list" }
        $Version = $stable.TrimStart("v")
        Write-Host "Auto-detected latest stable: v$Version" -ForegroundColor Cyan
    } finally { Pop-Location }
}

if ($Version -match "-(beta|rc|alpha)") {
    throw "Refusing to publish a prerelease tag ($Version) to winget. Beta/RC stay on the GitHub Releases page."
}

# ── 2. Build asset URL ───────────────────────────────────────────────────────
$assetName = "SignalRGBWallpaperSetup-$Version.exe"
$assetUrl  = "https://github.com/$ghUser/$ghRepo/releases/download/v$Version/$assetName"
Write-Host "Asset URL: $assetUrl" -ForegroundColor Cyan

# ── 3. Sanity-check the asset is reachable (avoids submitting a
#       manifest for an asset that's still uploading or got renamed) ──
try {
    $resp = Invoke-WebRequest -Uri $assetUrl -Method Head -ErrorAction Stop -MaximumRedirection 5
    if ($resp.StatusCode -ne 200) {
        throw "HEAD $assetUrl returned $($resp.StatusCode)"
    }
    Write-Host "Asset reachable (HEAD 200, $([math]::Round($resp.Headers['Content-Length'] / 1MB, 2)) MB)" -ForegroundColor Green
} catch {
    throw "Asset not reachable yet at $assetUrl — wait for the GitHub release to finish uploading, then re-run. ($_)"
}

# ── 4. Token resolution ──────────────────────────────────────────────────────
if (-not $Token) { $Token = $env:WINGETCREATE_GITHUB_TOKEN }
if (-not $Token -and -not $DryRun) {
    throw "No GitHub token. Set WINGETCREATE_GITHUB_TOKEN env var (PAT with public_repo scope) or pass -Token, or use -DryRun."
}

# ── 5. wingetcreate availability ─────────────────────────────────────────────
$wgc = Get-Command wingetcreate -ErrorAction SilentlyContinue
if (-not $wgc) {
    throw "wingetcreate not found on PATH. Install with: winget install Microsoft.WingetCreate"
}

# ── 6. Invoke ────────────────────────────────────────────────────────────────
$args = @(
    "update", $pkgId,
    "--version", $Version,
    "--urls", $assetUrl
)
if ($DryRun) {
    Write-Host "[DryRun] Would run: wingetcreate $($args -join ' ')" -ForegroundColor Yellow
    Write-Host "[DryRun] Would submit PR to microsoft/winget-pkgs with token: $($Token ? '<set>' : '<missing>')" -ForegroundColor Yellow
    return
}

$args += @("--submit", "--token", $Token)
Write-Host "Running wingetcreate update $pkgId --version $Version --submit …" -ForegroundColor Yellow
& wingetcreate @args
if ($LASTEXITCODE -ne 0) { throw "wingetcreate exited $LASTEXITCODE — check output above" }

Write-Host ""
Write-Host "Submitted. PR will appear at https://github.com/microsoft/winget-pkgs/pulls?q=$pkgId+v$Version" -ForegroundColor Green
Write-Host "Validation usually finishes within ~15 min; if the PR's checks go green it auto-merges." -ForegroundColor Green
