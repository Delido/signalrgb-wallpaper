# Maintainer-only helper: re-injects the Steam Workshop ID into the
# locally-deployed Wallpaper Engine project.json so the next
# "Share on Workshop" submit from WE's editor UPDATES the existing
# Workshop item instead of creating a new one.
#
# Background — the installer ships a fresh project.json with each
# release (so the bundled description / tags stay in sync with the
# feature set). That overwrite blows away the `workshopid` +
# `workshopurl` fields WE writes there after the first Workshop
# publish. End users don't care (they don't publish). But the
# maintainer does: without the workshopid linkage, WE treats the
# next submit as a brand-new item with a fresh Steam ID — orphaning
# every existing subscriber on the old item.
#
# Run this AFTER each installer run, BEFORE opening WE's editor to
# push an update.
#
#   pwsh installer\maintainer-restore-workshopid.ps1
#
# The Workshop ID is hard-coded below for this specific project —
# fork-friendly forks would override it. Not a secret; it's already
# in the public Steam URL.

[CmdletBinding()]
param(
    [string]$WorkshopId = "3729759521",
    [string]$ProjectPath = "C:\Program Files (x86)\Steam\steamapps\common\wallpaper_engine\projects\myprojects\signalrgb-glow\project.json"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ProjectPath)) {
    Write-Host "project.json not found at: $ProjectPath" -ForegroundColor Red
    Write-Host "Run the SignalRGB Wallpaper Bridge installer first (it copies the bundle into WE's myprojects folder)." -ForegroundColor Yellow
    exit 1
}

$json = Get-Content $ProjectPath -Raw | ConvertFrom-Json

$existingId = $json.PSObject.Properties.Match("workshopid").Value
if ($existingId -and $existingId -ne $WorkshopId) {
    Write-Host "WARN: project.json already has a different workshopid ($existingId) — overwriting with $WorkshopId" -ForegroundColor Yellow
}

# Add or overwrite both fields. ConvertTo-Json with -Depth 6 matches
# the depth build.ps1 uses, so the round-trip preserves nested data.
$json | Add-Member -NotePropertyName "workshopid"  -NotePropertyValue $WorkshopId                                  -Force
$json | Add-Member -NotePropertyName "workshopurl" -NotePropertyValue "steam://url/CommunityFilePage/$WorkshopId" -Force

$json | ConvertTo-Json -Depth 6 | Set-Content -Path $ProjectPath -Encoding UTF8

Write-Host "OK — project.json now points at Workshop item $WorkshopId" -ForegroundColor Green
Write-Host "Path: $ProjectPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next:" -ForegroundColor Yellow
Write-Host "  1. Open Wallpaper Engine" -ForegroundColor Yellow
Write-Host "  2. Open Wallpaper Editor" -ForegroundColor Yellow
Write-Host "  3. File -> Open Project -> the signalrgb-glow folder" -ForegroundColor Yellow
Write-Host "  4. Toolbar -> Share on Workshop -> verify it says 'Update existing item'" -ForegroundColor Yellow
Write-Host "  5. Fill changelog, Submit." -ForegroundColor Yellow
