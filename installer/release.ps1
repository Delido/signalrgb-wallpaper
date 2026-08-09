# Cut a release: verify, build, tag, publish.
#
# Replaces the hand-run sequence — run tests, build, commit, push, tag,
# gh release create, write notes — that the v2.4.x line was cut with.
# That sequence dropped things: the v2.4.2 release notes pointed users at
# a tray menu entry that had moved to the Configurator, and drifted from
# what bridge.py's RELEASE_NOTES said, because the two were written by
# hand at different times.
#
# The release notes here come from bridge.py's RELEASE_NOTES dict, so
# what GitHub shows and what the Configurator's "What's new" modal shows
# are the same text by construction.
#
# Usage:
#   pwsh installer\release.ps1 -DryRun        # verify + build, publish nothing
#   pwsh installer\release.ps1                # full cut
#   pwsh installer\release.ps1 -SkipBuild     # reuse installer_out\ artifacts
#
# Version comes from APP_VERSION in bridge.py. A version containing
# -beta / -rc is published as a GitHub prerelease and never reaches
# winget (patches stay on GitHub until the next minor cut anyway — see
# installer\winget-docs.md).
#
# Requirements: gh CLI authenticated, a clean working tree, Inno Setup
# for the build step.

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$SkipBuild,
    [switch]$SkipTests,
    # Publish even with uncommitted changes. Off by default: the tag
    # must describe what the asset was built from.
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$bridgePy = Join-Path $repoRoot "wallpaper_bridge\bridge.py"
$ghRepo   = "Delido/signalrgb-wallpaper"

function Step($msg) { Write-Host "`n=== $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  $msg" -ForegroundColor Yellow }

# Resolve gh once — it's frequently installed but absent from an
# already-open shell's PATH.
$ghCmd = Get-Command gh -ErrorAction SilentlyContinue
$ghExe = if ($ghCmd) { $ghCmd.Source } else { $null }
if (-not $ghExe) {
    foreach ($cand in @("$env:ProgramFiles\GitHub CLI\gh.exe",
                        "${env:ProgramFiles(x86)}\GitHub CLI\gh.exe",
                        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\gh.exe")) {
        if (Test-Path $cand) { $ghExe = $cand; break }
    }
}
if (-not $ghExe -and -not $DryRun) {
    throw "gh CLI not found. Install with: winget install GitHub.cli"
}

# ── 1. Version ───────────────────────────────────────────────────────────────
Step "Reading version"
$py = Get-Content $bridgePy -Raw
if ($py -notmatch '(?m)^APP_VERSION\s*=\s*"([^"]+)"') { throw "APP_VERSION not found in bridge.py" }
$version = $Matches[1]
if ($py -notmatch '(?m)^WALLPAPER_VERSION\s*=\s*"([^"]+)"') { throw "WALLPAPER_VERSION not found" }
$wallpaperVersion = $Matches[1]
$isPrerelease = $version -match '-(beta|rc|alpha)'
$tag = "v$version"

Ok "APP_VERSION       = $version$(if($isPrerelease){' (prerelease)'})"
Ok "WALLPAPER_VERSION = $wallpaperVersion"

# ── 2. Preflight ─────────────────────────────────────────────────────────────
Step "Preflight"

# RELEASE_NOTES entry — the Configurator reads this after every update,
# and we're about to use it as the GitHub release body.
if ($py -notmatch [regex]::Escape("`"$version`": {")) {
    throw "No RELEASE_NOTES entry for $version in bridge.py. The Configurator's 'What's new' modal would show a generic stub."
}
Ok "RELEASE_NOTES entry present"

$changelog = Join-Path $repoRoot "CHANGELOG.md"
if ((Get-Content $changelog -Raw) -notmatch [regex]::Escape("## [$version]")) {
    throw "No '## [$version]' heading in CHANGELOG.md"
}
Ok "CHANGELOG entry present"

Push-Location $repoRoot
try {
    $dirty = & git status --porcelain
    if ($dirty -and -not $AllowDirty) {
        Write-Host ($dirty | Out-String) -ForegroundColor DarkGray
        throw "Working tree is dirty. Commit first, or pass -AllowDirty."
    }
    if ($dirty) { Warn "Working tree is dirty (-AllowDirty)" } else { Ok "Working tree clean" }

    $existing = & git tag --list $tag
    if ($existing) { throw "Tag $tag already exists. Bump APP_VERSION or delete the tag." }
    Ok "Tag $tag is free"
} finally { Pop-Location }

# ── 3. Tests ─────────────────────────────────────────────────────────────────
if (-not $SkipTests) {
    Step "Test suite"
    Push-Location $repoRoot
    try {
        & python tests\run_all.py
        if ($LASTEXITCODE -ne 0) { throw "Tests failed — refusing to cut a release" }
        Ok "All suites passed"
    } finally { Pop-Location }
} else {
    Warn "Tests skipped (-SkipTests)"
}

# ── 4. Build ─────────────────────────────────────────────────────────────────
$installerExe = Join-Path $repoRoot "installer_out\SignalRGBWallpaperSetup-$version.exe"
if (-not $SkipBuild) {
    Step "Build"
    & (Join-Path $PSScriptRoot "build.ps1")
    if ($LASTEXITCODE -ne 0) { throw "build.ps1 failed" }
} else {
    Warn "Build skipped (-SkipBuild)"
}
if (-not (Test-Path $installerExe)) {
    throw "Installer not found at $installerExe$(if($SkipBuild){' — -SkipBuild needs a previous build'})"
}
$sizeMb = [math]::Round((Get-Item $installerExe).Length / 1MB, 1)
Ok "Installer: $([IO.Path]::GetFileName($installerExe)) ($sizeMb MB)"

# ── 5. Release notes ─────────────────────────────────────────────────────────
# Pull the English body straight out of bridge.py so GitHub and the
# in-app modal can't drift apart.
Step "Release notes"
$notesFile = Join-Path $repoRoot "installer_out\RELEASE_NOTES-$version.md"
$extractor = @"
import re, sys
sys.path.insert(0, r'$($repoRoot -replace "\\", "\\\\")\\wallpaper_bridge')
import importlib.util
spec = importlib.util.spec_from_file_location('b', r'$($bridgePy -replace "\\", "\\\\")')
m = importlib.util.module_from_spec(spec)
sys.modules['b'] = m
_err = sys.stderr
spec.loader.exec_module(m)
n = m.RELEASE_NOTES.get(m.APP_VERSION)
if not n:
    print('MISSING', file=_err); raise SystemExit(1)
body = n['body_en']
print(body, file=_err)
"@
$tmpPy = Join-Path $env:TEMP "extract-notes-$PID.py"
Set-Content -Path $tmpPy -Value $extractor -Encoding UTF8
try {
    # bridge.py hijacks stdout on import, so the extractor prints to
    # stderr and we capture that stream.
    $notesBody = & python $tmpPy 2>&1 | Where-Object { $_ -notmatch "module load failed" }
    if ($LASTEXITCODE -ne 0) { throw "Could not extract RELEASE_NOTES for $version" }
} finally { Remove-Item $tmpPy -ErrorAction SilentlyContinue }

$header = if ($isPrerelease) {
    "> **Prerelease.** Not offered as an update unless *Include beta versions* is enabled in the Configurator's System section.`n`n"
} else { "" }

# The re-import instructions belong on releases that actually changed
# the wallpaper page — i.e. where WALLPAPER_VERSION was bumped to match
# this release. Printing them on a bridge-only release sends users
# through a re-import and a WE re-apply for nothing, and it dilutes the
# notice on the releases that genuinely need it.
#
# Compare against the release's base version so a beta of a
# wallpaper-changing release still gets the notice: WALLPAPER_VERSION
# is "2.4.4" while APP_VERSION is "2.4.4-beta.1".
$baseVersion = ($version -split '-')[0]
$footer = "`n`n---`n`n"
if ($wallpaperVersion -eq $baseVersion) {
    $footer += @"
**Wallpaper Engine users:** this release changes the wallpaper page, which WE caches.
Subscribed on the Steam Workshop? Steam delivers the update — restart Steam to force a
check, then re-apply the wallpaper to your monitor. Imported locally, or on Lively?
Open the Configurator → **System** → **Re-import wallpaper bundles…**.

"@
} else {
    $footer += "Bridge-only release — no bundle re-import needed.`n`n"
}
$footer += "Full changelog: https://github.com/$ghRepo/blob/main/CHANGELOG.md"

Set-Content -Path $notesFile -Value ($header + ($notesBody -join "`n") + $footer) -Encoding UTF8
Ok "Notes written to $([IO.Path]::GetFileName($notesFile)) ($(($notesBody | Measure-Object).Count) lines from RELEASE_NOTES)"

# ── 6. Publish ───────────────────────────────────────────────────────────────
if ($DryRun) {
    Step "DryRun — nothing published"
    Write-Host "  Would tag:    $tag" -ForegroundColor DarkGray
    Write-Host "  Would create: gh release create $tag $(if($isPrerelease){'--prerelease'}else{'--latest'})" -ForegroundColor DarkGray
    Write-Host "  Would attach: $([IO.Path]::GetFileName($installerExe)) + .sha256" -ForegroundColor DarkGray
    Write-Host "  winget:       $(if($isPrerelease){'skipped (prerelease)'}else{'run installer\winget-publish.ps1 separately'})" -ForegroundColor DarkGray
    Write-Host "`nNotes preview:" -ForegroundColor DarkGray
    Get-Content $notesFile | Select-Object -First 12 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    return
}

Step "Publishing"
Push-Location $repoRoot
try {
    & git push origin HEAD
    if ($LASTEXITCODE -ne 0) { throw "git push failed" }
    Ok "Pushed to origin"

    $relArgs = @(
        "release", "create", $tag,
        $installerExe, "$installerExe.sha256",
        "--repo", $ghRepo,
        "--target", "main",
        "--title", "$tag",
        "--notes-file", $notesFile
    )
    $relArgs += if ($isPrerelease) { "--prerelease" } else { "--latest" }

    & $ghExe @relArgs
    if ($LASTEXITCODE -ne 0) { throw "gh release create failed" }
    Ok "Release published: https://github.com/$ghRepo/releases/tag/$tag"
} finally { Pop-Location }

Step "Next steps"
if ($isPrerelease) {
    Write-Host "  Prerelease — winget is skipped by design." -ForegroundColor DarkGray
} else {
    Write-Host "  winget:  pwsh installer\winget-publish.ps1" -ForegroundColor DarkGray
    Write-Host "           (patch releases usually wait for the next minor — see winget-docs.md)" -ForegroundColor DarkGray
}
if ($wallpaperVersion -eq $baseVersion) {
    Write-Host "  Workshop: WALLPAPER_VERSION changed — the WE item needs re-uploading." -ForegroundColor Yellow
    Write-Host "            Run installer\maintainer-restore-workshopid.ps1 FIRST, or WE" -ForegroundColor Yellow
    Write-Host "            creates a new Workshop item instead of updating the existing one." -ForegroundColor Yellow
}
