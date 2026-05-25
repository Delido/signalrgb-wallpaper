# Grant MSIX-Lively a loopback (127.0.0.1) exemption so its WebView2
# wallpaper page can reach the SignalRGB Wallpaper Bridge.
#
# Background — MSIX apps run inside a Windows AppContainer sandbox. The
# default AppContainer firewall rule blocks outbound loopback traffic,
# so the wallpaper page's `ws://127.0.0.1:17320/` connection silently
# fails. Symptoms users see:
#   • No glow / no widgets on Lively (Microsoft Store build only)
#   • Pause-on-fullscreen never fires (bridge can't push WS msgs)
#   • Configurator changes don't reach the screen
# The exact same wallpaper bundle works fine on the GitHub-installer
# build of Lively because that one isn't sandboxed.
#
# Fix is a one-shot system call:
#   CheckNetIsolation.exe LoopbackExempt -a -n=<PackageFamilyName>
# Persists across reboots, survives Lively updates. No admin required.
#
# Invoked by:
#   • Installer [Run] section after a successful install/upgrade
#   • Tray entry "Re-import wallpaper bundles now…" (chained call)
#   • Manual maintainer use:
#       pwsh installer\msix-lively-loopback-exempt.ps1
#
# Exit codes:
#   0 — exemption added OR not needed (no MSIX-Lively present)
#   1 — MSIX-Lively detected but CheckNetIsolation failed

[CmdletBinding()]
param([switch]$Quiet)

$ErrorActionPreference = "Continue"

function Write-Status {
    param([string]$Message, [string]$Color = "White")
    if (-not $Quiet) {
        Write-Host $Message -ForegroundColor $Color
    }
}

Write-Status "SignalRGB Wallpaper Bridge — MSIX-Lively loopback exemption" "Cyan"

# Resolve the MSIX-Lively Package Family Name (PFN). Get-AppxPackage is
# the canonical API; it returns objects with .PackageFamilyName as the
# `<Name>_<PublisherHash>` token CheckNetIsolation wants.
$pkg = $null
try {
    $pkg = Get-AppxPackage -Name "*rocksdanister.LivelyWallpaper*" -ErrorAction SilentlyContinue |
           Select-Object -First 1
} catch {
    # Get-AppxPackage isn't always available (e.g. PowerShell 7 on
    # systems without the Appx module). Fall through to the manual
    # Packages-folder scan below.
}

$pfn = $null
if ($pkg -and $pkg.PackageFamilyName) {
    $pfn = $pkg.PackageFamilyName
    Write-Status "  Detected MSIX Lively: $pfn" "DarkCyan"
} else {
    # Fallback: scan %LOCALAPPDATA%\Packages for the publisher-prefixed
    # directory name (e.g. 12030rocksdanister.LivelyWallpaper_97hta09mmv6hy)
    # and derive the PFN from that. The Packages-folder name is NOT the
    # PFN — it has the numeric publisher ID prefix that CheckNetIsolation
    # doesn't accept — so we strip the leading digits.
    $pkgRoot = Join-Path $env:LOCALAPPDATA "Packages"
    if (Test-Path $pkgRoot) {
        $pkgDir = Get-ChildItem -Path $pkgRoot -Directory `
                                -Filter "*rocksdanister.LivelyWallpaper_*" `
                                -ErrorAction SilentlyContinue |
                  Select-Object -First 1
        if ($pkgDir) {
            # Strip the leading numeric publisher ID prefix. Real name is
            # always `<digits>rocksdanister.LivelyWallpaper_<hash>`.
            $pfn = ($pkgDir.Name -replace '^\d+', '')
            Write-Status "  Detected MSIX Lively (folder probe): $pfn" "DarkCyan"
        }
    }
}

if (-not $pfn) {
    Write-Status "No MSIX-Lively detected — nothing to do." "DarkGray"
    exit 0
}

# Check whether the exemption already exists. CheckNetIsolation has no
# query-by-PFN flag, so we list all loopback-exempted AppContainers and
# grep for ours. The output format is fixed across Windows builds:
#   [<n>] -----------------------------------------------------------------
#       Name: AppContainer.<something>
#       SID:  S-1-15-...
# We just look for the PFN substring (it appears in the SID derivation
# for the AppContainer name on Lively's package).
$alreadyExempt = $false
try {
    $existing = & CheckNetIsolation.exe LoopbackExempt -s 2>&1 | Out-String
    if ($existing -match [Regex]::Escape($pfn)) {
        $alreadyExempt = $true
    }
} catch {
    # If CheckNetIsolation isn't present we'll find out on the -a call below.
}

if ($alreadyExempt) {
    Write-Status "  Loopback exemption already present — skipping." "Green"
    exit 0
}

Write-Status "  Adding loopback exemption…" "Green"
try {
    $output = & CheckNetIsolation.exe LoopbackExempt -a -n=$pfn 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        Write-Status "  ERROR: CheckNetIsolation exit=$LASTEXITCODE" "Red"
        Write-Status $output "DarkRed"
        exit 1
    }
    Write-Status "  Done. Restart Lively to pick up the new permission." "Green"
} catch {
    Write-Status "  ERROR running CheckNetIsolation: $_" "Red"
    exit 1
}

exit 0
