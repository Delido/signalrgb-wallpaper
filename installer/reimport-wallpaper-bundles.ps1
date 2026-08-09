# Re-import the SignalRGB Glow wallpaper bundles into Lively (and
# touch the WE project to nudge Wallpaper Engine into re-loading).
#
# Background — the installer drops fresh ZIPs into
# {app}\Lively wallpapers\ and a fresh project folder into
# Steam\steamapps\common\wallpaper_engine\projects\myprojects\, but
# both hosts cache the OLD extracted / loaded copy:
#   • Lively extracts each ZIP into a random-hash folder once;
#     re-overwriting the ZIP doesn't propagate.
#   • Wallpaper Engine reads project.json + index.html at first
#     apply and caches them in memory.
# So after every wallpaper-side code update the user had to delete +
# re-import in Lively, and unsubscribe + re-apply in WE.
#
# This script automates step 1 (Lively re-import via its CLI) and
# step 2 (touching WE's project version so the host invalidates its
# cache on the next apply). WE doesn't expose a public reload API so
# the user still has to right-click the wallpaper → re-apply, but
# the version-bump means WE then picks up the NEW files.
#
# Invoked by:
#   • Installer [Run] section after a successful upgrade
#   • Tray entry "Re-import wallpaper bundles now…" under Advanced
#   • Manual maintainer use:
#       pwsh installer\reimport-wallpaper-bundles.ps1
#
# Exit codes:
#   0 — all detected hosts updated cleanly
#   1 — neither Lively nor a WE project folder was detected
#   2 — Lively CLI invocation failed for at least one ZIP
#   3 — WE project.json patch failed
#   4 — nothing failed, but the user's WE copy is a Steam Workshop
#       subscription we can't touch (v2.4.3). Steam ships the update
#       itself; the caller should say so rather than report success.

[CmdletBinding()]
param(
    # v2.2.1: install dir moved to Program Files (was per-user
    # %LOCALAPPDATA%\Programs\SignalRGBWallpaperBridge — note the
    # bonus "Bridge" suffix that never actually matched the real
    # install path, so this default was silently broken for any
    # manual CLI invocation before v2.2.1). Bridge.py always
    # passes an explicit -AppDir derived from sys.executable, so
    # the default only kicks in when a user runs this from a
    # shell directly.
    [string]$AppDir = "$env:ProgramFiles\SignalRGBWallpaper",
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"

function Write-Status {
    param([string]$Message, [string]$Color = "White")
    if (-not $Quiet) {
        Write-Host $Message -ForegroundColor $Color
    }
}

Write-Status "SignalRGB Wallpaper Bridge — re-import bundles" "Cyan"
Write-Status "App dir: $AppDir" "DarkGray"

$livelyZipsDir = Join-Path $AppDir "Lively wallpapers"
$weStageDir    = Join-Path $AppDir "Wallpaper Engine wallpapers"

$anyHostUpdated = $false
$livelyError    = $false
$weError        = $false

# ── Lively path ─────────────────────────────────────────────────────────────
# Two Lively variants ship in the wild:
#   • GitHub installer build — `lively.exe` exposes an `--import-from-
#     zip` CLI we can call directly.
#   • MSIX (Microsoft Store) build — sandboxed AppContainer, no
#     externally-invokable CLI. For these users we extract the ZIPs
#     directly into Lively's library folder (the one MSIX-Lively
#     reads from, which is the LocalCache redirection target — NOT
#     LocalState; that's a long-standing trap-door in MSIX virtualization).
# Both paths land at the same end result: Lively's library shows the
# four `SignalRGB Glow – Screen N` entries with the fresh JS.

$livelyExe = $null
$livelyCandidates = @(
    "$env:LOCALAPPDATA\Programs\Lively Wallpaper\Lively.exe",
    "$env:LOCALAPPDATA\Programs\Lively Wallpaper\livelywpf\Lively.exe",
    "$env:ProgramFiles\Lively Wallpaper\Lively.exe",
    "${env:ProgramFiles(x86)}\Lively Wallpaper\Lively.exe"
)
foreach ($candidate in $livelyCandidates) {
    if (Test-Path $candidate) {
        $livelyExe = $candidate
        break
    }
}

# MSIX detection: probe Packages\rocksdanister.LivelyWallpaper_* for
# either LocalCache (the legacy-write redirection target) or LocalState
# (some Lively builds store there directly). LocalCache wins because
# that's what MSIX Lively actually reads from for its library scan.
$livelyMsixLibrary = $null
$pkgRoot = Join-Path $env:LOCALAPPDATA "Packages"
if (Test-Path $pkgRoot) {
    # MS Store prefixes every package name with a numeric publisher
    # ID, so the real directory is e.g.
    # `12030rocksdanister.LivelyWallpaper_97hta09mmv6hy`. Leading `*`
    # in the filter catches that prefix; without it the probe missed
    # every MSIX Lively install.
    $pkgDir = Get-ChildItem -Path $pkgRoot -Directory `
                            -Filter "*rocksdanister.LivelyWallpaper_*" `
                            -ErrorAction SilentlyContinue |
              Select-Object -First 1
    if ($pkgDir) {
        $msixCandidates = @(
            (Join-Path $pkgDir.FullName "LocalCache\Local\Lively Wallpaper\Library\wallpapers"),
            (Join-Path $pkgDir.FullName "LocalState\Library\wallpapers")
        )
        foreach ($candidate in $msixCandidates) {
            if (Test-Path $candidate) {
                $livelyMsixLibrary = $candidate
                break
            }
        }
        # Path may not exist yet on a fresh Lively-MSIX install; create
        # the LocalCache variant since that's where MSIX redirection
        # will route Lively's own writes.
        if (-not $livelyMsixLibrary) {
            $livelyMsixLibrary = $msixCandidates[0]
            try {
                New-Item -ItemType Directory -Path $livelyMsixLibrary -Force | Out-Null
            } catch {
                Write-Status "  WARN: couldn't create MSIX Lively library path $livelyMsixLibrary - $_" "Yellow"
                $livelyMsixLibrary = $null
            }
        }
    }
}

# ── MSIX-Lively path: extract ZIPs straight into the library folder ──
if ($livelyMsixLibrary -and (Test-Path $livelyZipsDir)) {
    Write-Status "Lively (MSIX) library: $livelyMsixLibrary" "Green"
    $zips = Get-ChildItem -Path $livelyZipsDir -Filter "SignalRGB_Glow_Screen*.zip" -ErrorAction SilentlyContinue
    foreach ($zip in $zips) {
        try {
            # Derive screen folder name from the ZIP name. The ZIP root
            # already contains the per-screen identity (LivelyInfo.json
            # baked at build time), so we extract into a deterministic
            # subfolder matching the screen index.
            $screenNum = if ($zip.Name -match "Screen(\d)") { $Matches[1] } else { "1" }
            $dest = Join-Path $livelyMsixLibrary ("signalrgb-glow-screen-$screenNum")
            if (Test-Path $dest) {
                Remove-Item -Path $dest -Recurse -Force -ErrorAction SilentlyContinue
            }
            Expand-Archive -Path $zip.FullName -DestinationPath $dest -Force
            Write-Status "  extracted $($zip.Name) -> $dest" "DarkCyan"
        } catch {
            Write-Status "    ERROR extracting $($zip.Name): $_" "Red"
            $livelyError = $true
        }
    }
    $anyHostUpdated = $true
    Write-Status "  MSIX Lively: restart Lively (or use its 'Refresh Library' option) to pick up the new bundles." "DarkGray"
}

if ($livelyExe -and (Test-Path $livelyZipsDir)) {
    # Only re-import if Lively is ALREADY running. Users with both
    # Lively + WE installed who actively use only one shouldn't have
    # the other auto-launched on every update — that's the bug a real
    # user just reported (WE-only setup, Lively auto-launched).
    # Skip silently when Lively isn't up; the new ZIPs are sitting
    # in $livelyZipsDir for the next manual import whenever the user
    # actually opens Lively.
    $livelyRunning = $null -ne (Get-Process -Name "Lively","Livelywpf" -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $livelyRunning) {
        Write-Status "Lively not running — skipping CLI re-import (would otherwise force-launch the app). ZIPs are at $livelyZipsDir for the next manual import." "DarkGray"
    } else {
        Write-Status "Lively CLI: $livelyExe (process detected — running re-import)" "Green"
        $zips = Get-ChildItem -Path $livelyZipsDir -Filter "SignalRGB_Glow_Screen*.zip" -ErrorAction SilentlyContinue
        if ($zips.Count -eq 0) {
            Write-Status "  No SignalRGB_Glow ZIPs found in $livelyZipsDir — skipping Lively re-import." "Yellow"
        } else {
            foreach ($zip in $zips) {
                try {
                    # Lively's --import flag accepts ZIP paths and de-duplicates
                    # by name. The pre-existing extracted folder isn't auto-
                    # deleted but Lively does swap which hash folder the
                    # library entry points at on re-import.
                    Write-Status "  --import $($zip.Name)" "DarkCyan"
                    & $livelyExe --import $zip.FullName 2>&1 | Out-Null
                    if ($LASTEXITCODE -ne 0) {
                        Write-Status "    WARN: lively.exe exit=$LASTEXITCODE for $($zip.Name)" "Yellow"
                        $livelyError = $true
                    }
                    Start-Sleep -Milliseconds 250
                } catch {
                    Write-Status "    ERROR re-importing $($zip.Name): $_" "Red"
                    $livelyError = $true
                }
            }
            $anyHostUpdated = $true
        }
    }
}
# Note: the old "open the wallpapers folder for manual drag-import"
# fallback is gone — for end users on the auto-update path, popping
# Explorer mid-update is just as annoying as auto-launching Lively.
# Users who want the manual drag-import can run the tray entry
# explicitly, which still surfaces the folder via the log.

# ── Wallpaper Engine path ───────────────────────────────────────────────────
# WE has no reload-API. Workaround: bump the version field inside
# the project's project.json. Next time WE loads the project (either
# on its own next start or via user re-apply) it detects the
# version change and re-reads from disk instead of cache.
#
# Steam path is the canonical install location; the staging folder
# under {app}\Wallpaper Engine wallpapers is what the installer
# copies fresh files into.

$weMyProjects = "${env:ProgramFiles(x86)}\Steam\steamapps\common\wallpaper_engine\projects\myprojects\signalrgb-glow"
if (Test-Path $weMyProjects) {
    $weProjectJson = Join-Path $weMyProjects "project.json"
    if (Test-Path $weProjectJson) {
        try {
            $json = Get-Content $weProjectJson -Raw | ConvertFrom-Json
            $oldVer = if ($json.PSObject.Properties.Match("version").Count) { $json.version } else { 0 }
            $newVer = [int]$oldVer + 1
            $json | Add-Member -NotePropertyName "version" -NotePropertyValue $newVer -Force
            $json | ConvertTo-Json -Depth 10 | Set-Content -Path $weProjectJson -Encoding UTF8
            Write-Status "WE project.json version bumped: $oldVer → $newVer" "Green"
            Write-Status "  Open Wallpaper Engine → My Wallpapers → right-click SignalRGB Glow → Set as wallpaper to apply the update." "DarkGray"
            $anyHostUpdated = $true
            # v2.4.3: a locally imported project WAS updated here, so the
            # Workshop notice below must not downgrade the exit code —
            # a user with both copies is genuinely done.
            $weProjectPatched = $true
        } catch {
            Write-Status "ERROR patching WE project.json: $_" "Red"
            $weError = $true
        }
    } else {
        Write-Status "WE myprojects folder exists but no project.json inside — skipping." "Yellow"
    }
} else {
    Write-Status "Wallpaper Engine not detected (no myprojects\signalrgb-glow folder) — skipping WE path." "DarkGray"
}

# ── Steam Workshop subscription check ──────────────────────────────────────
# v2.4.3: the block above only ever looked in myprojects\, i.e. a locally
# imported project. Users who SUBSCRIBED to the Workshop item have their
# copy under steamapps\workshop\content\431960\<workshop-id>\ instead, and
# nothing here can update it: the files are Steam-managed, and the
# installer doesn't write there either. Pre-2.4.3 those users clicked
# "Re-import wallpaper bundles", got a success toast, and nothing
# happened — which is exactly how the v2.4.2 fix failed to reach the
# person who reported the bug it fixed.
#
# We can't fix their copy, but we can stop lying about it and tell them
# what actually works: Steam ships the update, then they re-apply.
$weWorkshopRoot = "${env:ProgramFiles(x86)}\Steam\steamapps\workshop\content\431960"
$subscribedCopy = $null
if (Test-Path $weWorkshopRoot) {
    foreach ($dir in Get-ChildItem $weWorkshopRoot -Directory -ErrorAction SilentlyContinue) {
        $pj = Join-Path $dir.FullName "project.json"
        if (-not (Test-Path $pj)) { continue }
        try {
            $meta = Get-Content $pj -Raw -ErrorAction Stop | ConvertFrom-Json
        } catch { continue }
        # Match on title rather than workshop id: the id changes if the
        # item is ever re-published, the title is what users recognise.
        if ($meta.title -and $meta.title -match 'SignalRGB') {
            $subscribedCopy = [pscustomobject]@{
                Path  = $dir.FullName
                Id    = $dir.Name
                Title = $meta.title
            }
            break
        }
    }
}

if ($subscribedCopy) {
    Write-Status "" "Gray"
    Write-Status "NOTE: you're subscribed to '$($subscribedCopy.Title)' on the Steam Workshop" "Yellow"
    Write-Status "  (item $($subscribedCopy.Id))" "DarkGray"
    Write-Status "  That copy is managed by Steam and cannot be updated from here." "Yellow"
    Write-Status "  Steam downloads new versions automatically — restart Steam to force a check." "Yellow"
    Write-Status "  Then re-apply the wallpaper in Wallpaper Engine to load it." "Yellow"
    # Counts as a detected host: the user has a working WE setup, so
    # "no wallpaper hosts detected" (exit 1) would be plainly wrong and
    # would surface as a failure toast.
    $anyHostUpdated = $true
    $weSubscribed = $true
}

# ── MSIX-Lively loopback exemption ─────────────────────────────────────────
# Re-running the exemption is idempotent — the script no-ops if MSIX-Lively
# isn't installed or the exemption is already in place — so call it
# unconditionally from the re-import path. This catches the case where the
# user installed MSIX-Lively *after* the bridge was already installed.
$loopbackScript = Join-Path $AppDir "msix-lively-loopback-exempt.ps1"
if (Test-Path $loopbackScript) {
    Write-Status "Running MSIX-Lively loopback-exemption helper…" "Cyan"
    try {
        & $loopbackScript -Quiet
    } catch {
        Write-Status "  WARN: loopback exempt helper failed: $_" "Yellow"
    }
}

# ── Result ─────────────────────────────────────────────────────────────────
if (-not $anyHostUpdated) {
    Write-Status "No wallpaper hosts detected (neither Lively nor WE)." "Red"
    exit 1
}
if ($livelyError) { exit 2 }
if ($weError)     { exit 3 }
# v2.4.3: exit 4 — everything we could touch was updated, but the user
# also has a Steam Workshop subscription we can't reach. Distinct from 0
# so the tray can say "Steam will deliver it, then re-apply" instead of
# a bare "done" that leaves them believing they're already up to date.
if ($weSubscribed -and -not $weProjectPatched) { exit 4 }
Write-Status "Done." "Green"
exit 0
