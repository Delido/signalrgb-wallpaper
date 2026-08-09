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
    # PowerShell 7 returns headers as string arrays even for single-value
    # headers like Content-Length; coerce + cast before the MB divide so
    # the friendly print doesn't blow up. Best-effort — if the header
    # isn't present we just skip the size line.
    $clRaw = $resp.Headers['Content-Length']
    if ($clRaw -is [array]) { $clRaw = $clRaw[0] }
    $clBytes = 0L
    if ([long]::TryParse([string]$clRaw, [ref]$clBytes) -and $clBytes -gt 0) {
        Write-Host ("Asset reachable (HEAD 200, {0:N2} MB)" -f ($clBytes / 1MB)) -ForegroundColor Green
    } else {
        Write-Host "Asset reachable (HEAD 200)" -ForegroundColor Green
    }
} catch {
    throw "Asset not reachable yet at $assetUrl — wait for the GitHub release to finish uploading, then re-run. ($_)"
}

# ── 4. Token resolution ──────────────────────────────────────────────────────
# v1.3.0: wingetcreate has its own cached-auth flow (`wingetcreate token
# --store` / interactive browser OAuth on first --submit), so a token
# here is now OPTIONAL — if neither -Token nor $env:WINGETCREATE_GITHUB_TOKEN
# is set we let wingetcreate fall back to its cache. The check is kept
# in -DryRun to make the planned-flow output explicit.
if (-not $Token) { $Token = $env:WINGETCREATE_GITHUB_TOKEN }

# ── 5. wingetcreate availability ─────────────────────────────────────────────
$wgc = Get-Command wingetcreate -ErrorAction SilentlyContinue
if (-not $wgc) {
    throw "wingetcreate not found on PATH. Install with: winget install Microsoft.WingetCreate"
}

# ── 6. Invoke ────────────────────────────────────────────────────────────────
# v1.3.0: the existing manifest declares Architecture: x64 with one
# installer entry, but wingetcreate auto-detects the Inno wrapper exe
# as x86 (Inno's bootloader is 32-bit even when the payload is 64-bit,
# which our PyInstaller --onedir Python build is). Force-match by
# appending `|x64` so wingetcreate maps the new installer onto the
# existing x64 row.
#
# v2.2.1: the pre-2.2.1 manifest carried `Scope: user`. v2.2.1 moved
# the install dir to Program Files and requires admin, so the manifest
# scope must flip to `machine` — otherwise `winget upgrade` would try
# to install with --scope user, hit the elevation requirement, and
# either silently fail or strand users on the old version. Pipe-
# override the scope so wingetcreate overrides the inherited value.
#
# v2.4.3: that pipe-override does NOT work. wingetcreate prints
# "Überschreiben … mit Bereich Machine" and then writes `Scope: user`
# anyway, inherited from the previous manifest — so every release from
# v2.2.1 onward shipped the wrong scope, silently, for three years'
# worth of versions. Verified against the published 2.4.0 manifest.
# The pipe stays (it costs nothing and pins the architecture, which
# does work), but the scope is now patched into the generated YAML
# below and verified before submit.
$urlSpec = $assetUrl + "|x64|machine"
# Renamed from $args to $wgcArgs — $args is a PowerShell automatic
# variable (the unbound-positional-args collection inside a function /
# script block); reassigning it triggers a PSScriptAnalyzer warning
# and can interact weirdly with nested scopes.
$wgcArgs = @(
    "update", $pkgId,
    "--version", $Version,
    "--urls", $urlSpec
)
if ($DryRun) {
    Write-Host "[DryRun] Would run: wingetcreate $($wgcArgs -join ' ') --submit" -ForegroundColor Yellow
    $tokenState = if ($Token) { '<set>' } else { '<wingetcreate cache>' }
    Write-Host "[DryRun] Token state: $tokenState" -ForegroundColor Yellow
    return
}

# v2.4.3: sync the fork before submitting.
#
# wingetcreate branches the PR off YOUR fork of microsoft/winget-pkgs.
# That fork is a snapshot from whenever you last pushed, and winget-pkgs
# takes several hundred commits a day, so after a few weeks between
# releases the fork is tens of thousands of commits behind and the
# submit fails with "Das geforkte Repository konnte nicht mit den
# Upstreamcommits synchronisiert werden". The v2.4.2 push hit exactly
# this at 17 229 commits behind.
#
# `gh repo sync` is idempotent — a fork that's already level is a no-op —
# so this runs unconditionally rather than trying to detect the drift.
# Null-conditional (?.) is PowerShell 7 only; this script has to parse
# under Windows PowerShell 5.1 too.
$ghCmd = Get-Command gh -ErrorAction SilentlyContinue
$ghExe = if ($ghCmd) { $ghCmd.Source } else { $null }
if (-not $ghExe) {
    foreach ($cand in @("$env:ProgramFiles\GitHub CLI\gh.exe",
                        "${env:ProgramFiles(x86)}\GitHub CLI\gh.exe",
                        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\gh.exe")) {
        if (Test-Path $cand) { $ghExe = $cand; break }
    }
}
if ($ghExe) {
    Write-Host "Syncing $ghUser/winget-pkgs with upstream…" -ForegroundColor Cyan
    try {
        & $ghExe repo sync "$ghUser/winget-pkgs" --source "microsoft/winget-pkgs" --branch master 2>&1 |
            ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  WARN: fork sync returned $LASTEXITCODE — submitting anyway" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  WARN: fork sync failed ($_) — submitting anyway" -ForegroundColor Yellow
    }
} else {
    Write-Host "gh CLI not found — skipping fork sync. If the submit fails with" -ForegroundColor Yellow
    Write-Host "an upstream-sync error, sync $ghUser/winget-pkgs manually." -ForegroundColor Yellow
}

# ── 7. Generate, patch, verify, then submit ──────────────────────────────────
# Split into two wingetcreate calls so the scope fix lands in the YAML
# that actually gets submitted. `update` without --submit writes the
# manifest tree under .\manifests\; `submit` pushes that exact tree.
$manifestDir = Join-Path $repoRoot "manifests\d\Delido\SignalRGBWallpaper\$Version"
if (Test-Path $manifestDir) { Remove-Item $manifestDir -Recurse -Force }

Push-Location $repoRoot
try {
    Write-Host "Generating manifest…" -ForegroundColor Yellow
    & wingetcreate @wgcArgs
    if ($LASTEXITCODE -ne 0) { throw "wingetcreate update exited $LASTEXITCODE — check output above" }

    $installerYaml = Join-Path $manifestDir "$pkgId.installer.yaml"
    if (-not (Test-Path $installerYaml)) {
        throw "Expected generated manifest at $installerYaml but it isn't there"
    }

    # Force Scope + ElevationRequirement. The installer sets
    # PrivilegesRequired=admin and installs into Program Files, so a
    # `user`-scoped manifest makes `winget upgrade` pick an install mode
    # the package can't satisfy.
    $yaml = Get-Content $installerYaml -Raw
    if ($yaml -match '(?m)^Scope:\s*\S+') {
        $yaml = $yaml -replace '(?m)^Scope:\s*\S+', 'Scope: machine'
    } else {
        $yaml = $yaml -replace '(?m)^(InstallerType:\s*\S+)', "`$1`nScope: machine"
    }
    if ($yaml -notmatch '(?m)^ElevationRequirement:') {
        $yaml = $yaml -replace '(?m)^(Scope:\s*machine)', "`$1`nElevationRequirement: elevationRequired"
    }
    Set-Content -Path $installerYaml -Value $yaml -Encoding UTF8 -NoNewline

    # Verify rather than trust: this is the exact check that would have
    # caught the silent v2.2.1-onward regression.
    $check = Get-Content $installerYaml -Raw
    if ($check -notmatch '(?m)^Scope:\s*machine') {
        throw "Scope is still not 'machine' after patching — refusing to submit $installerYaml"
    }
    Write-Host "  Scope: machine + ElevationRequirement: elevationRequired" -ForegroundColor Green

    Write-Host "Validating manifest…" -ForegroundColor Yellow
    & winget validate --manifest $manifestDir
    if ($LASTEXITCODE -ne 0) { throw "winget validate rejected the manifest" }

    $submitArgs = @("submit", "--prtitle", "$pkgId version $Version", $manifestDir)
    if ($Token) { $submitArgs += @("--token", $Token) }
    Write-Host "Submitting PR…" -ForegroundColor Yellow
    & wingetcreate @submitArgs
    if ($LASTEXITCODE -ne 0) { throw "wingetcreate submit exited $LASTEXITCODE — check output above" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Submitted. PR will appear at https://github.com/microsoft/winget-pkgs/pulls?q=$pkgId+v$Version" -ForegroundColor Green
Write-Host "Validation usually finishes within ~15 min; if the PR's checks go green it auto-merges." -ForegroundColor Green
