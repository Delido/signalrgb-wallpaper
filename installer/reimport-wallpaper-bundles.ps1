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

[CmdletBinding()]
param(
    [string]$AppDir = "$env:LOCALAPPDATA\Programs\SignalRGBWallpaperBridge",
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
    $pkgDir = Get-ChildItem -Path $pkgRoot -Directory `
                            -Filter "rocksdanister.LivelyWallpaper_*" `
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

# ── Result ─────────────────────────────────────────────────────────────────
if (-not $anyHostUpdated) {
    Write-Status "No wallpaper hosts detected (neither Lively nor WE)." "Red"
    exit 1
}
if ($livelyError) { exit 2 }
if ($weError)     { exit 3 }
Write-Status "Done." "Green"
exit 0
