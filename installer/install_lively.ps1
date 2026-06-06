#requires -Version 5.1
<#
install_lively.ps1

Downloads + silent-installs the latest Lively Wallpaper from GitHub
Releases. Invoked from Inno Setup's CurStepChanged(ssInstall) hook
when the user opted into auto-installing Lively AND no existing
install was detected. Runs BEFORE Inno's [Files] section so the
subsequent auto-import (`signalrgb-glow-screen-*\`) lands in a
freshly-created Lively library.

Exit codes:
  0 — success or user already had Lively installed (no-op)
  2 — GitHub Releases API unreachable / network down
  3 — no usable Lively setup asset in the latest release
  4 — Lively setup ran but its exit code wasn't 0
  9 — anything else

Designed to fail closed: a hard exit code stops Inno's install chain,
so we use a soft non-zero return + write status to a file the wizard
can read, letting the user proceed with manual install instead of
killing their session.
#>

[CmdletBinding()]
param(
    [string]$StatusFile = $null
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

function Write-Status {
    param([string]$msg)
    Write-Host "[install_lively] $msg"
    if ($StatusFile) {
        try { Add-Content -Path $StatusFile -Value $msg -Encoding UTF8 } catch {}
    }
}

try {
    Write-Status "Querying GitHub Releases for the latest Lively Wallpaper…"
    $api = "https://api.github.com/repos/rocksdanister/lively/releases/latest"
    $hdrs = @{ "User-Agent" = "SignalRGBWallpaperBootstrapper"; "Accept" = "application/vnd.github+json" }
    $rel = $null
    try {
        $rel = Invoke-RestMethod -Uri $api -Headers $hdrs -TimeoutSec 30
    } catch {
        Write-Status "GitHub Releases API unreachable: $_"
        exit 2
    }
    # Lively ships its installer as `lively_setup_x86_x64_*.exe`. Newer
    # builds use different naming so fall back to any `*setup*.exe`.
    $asset = $rel.assets | Where-Object { $_.name -like "lively_setup_*.exe" } | Select-Object -First 1
    if (-not $asset) {
        $asset = $rel.assets | Where-Object { $_.name -match "(?i)setup.*\.exe$" } | Select-Object -First 1
    }
    if (-not $asset) {
        Write-Status "No usable Lively setup asset in the latest release."
        exit 3
    }
    $sizeMB = [math]::Round($asset.size / 1MB, 1)
    Write-Status "Downloading $($asset.name) ($sizeMB MB)…"
    $tmp = Join-Path $env:TEMP $asset.name
    try {
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp `
                          -UseBasicParsing -TimeoutSec 600 -Headers $hdrs
    } catch {
        Write-Status "Download failed: $_"
        exit 2
    }
    Write-Status "Running silent Lively installer…"
    # Lively's installer is Inno Setup based; /VERYSILENT suppresses the
    # progress window, /SUPPRESSMSGBOXES blocks confirmation prompts,
    # /NORESTART skips any auto-reboot the inner installer might want.
    $p = Start-Process -FilePath $tmp -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
    ) -Wait -PassThru
    if ($p.ExitCode -ne 0) {
        Write-Status "Lively setup exit code $($p.ExitCode) — manual install may be needed."
        exit 4
    }
    Write-Status "Lively installed successfully."
    # Clean up the temp file (best-effort; if the file is locked the next
    # %TEMP% cleanup pass will get it).
    try { Remove-Item $tmp -Force -ErrorAction SilentlyContinue } catch {}
    exit 0
} catch {
    Write-Status "Unexpected failure: $_"
    exit 9
}
