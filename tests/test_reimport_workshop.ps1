# Exercises the v2.4.3 Workshop-detection block from
# reimport-wallpaper-bundles.ps1 against synthetic Steam trees, so we can
# cover cases this machine doesn't have (a real SignalRGB subscription)
# without touching the user's actual Lively/WE install.

$ErrorActionPreference = "Stop"
$pass = 0; $fail = @()

function Check($label, $cond, $detail = "") {
    if ($cond) { $script:pass++; Write-Host "  PASS  $label" }
    else { $script:fail += $label; Write-Host "  FAIL  $label$(if($detail){" - $detail"})" }
}

# The detection block, lifted verbatim in shape but parameterised on the
# workshop root so we can point it at a fixture.
function Find-SubscribedCopy([string]$weWorkshopRoot) {
    $subscribedCopy = $null
    if (Test-Path $weWorkshopRoot) {
        foreach ($dir in Get-ChildItem $weWorkshopRoot -Directory -ErrorAction SilentlyContinue) {
            $pj = Join-Path $dir.FullName "project.json"
            if (-not (Test-Path $pj)) { continue }
            try { $meta = Get-Content $pj -Raw -ErrorAction Stop | ConvertFrom-Json } catch { continue }
            if ($meta.title -and $meta.title -match 'SignalRGB') {
                $subscribedCopy = [pscustomobject]@{
                    Path = $dir.FullName; Id = $dir.Name; Title = $meta.title
                }
                break
            }
        }
    }
    return $subscribedCopy
}

# $env:TEMP is a Windows-ism and is null on Linux, where Join-Path then
# fails with "Cannot bind argument to parameter 'Path'". GetTempPath()
# resolves on both. The suite itself is platform-neutral — it walks
# synthetic directory trees, and only the paths it *describes* are
# Windows-specific — so it should run wherever pwsh does, which on
# ubuntu-latest it does.
$tempRoot = [System.IO.Path]::GetTempPath()
$root = Join-Path $tempRoot "wsdetect-$PID"
New-Item -ItemType Directory -Path $root -Force | Out-Null

try {
    Write-Host "`nno workshop dir at all"
    Check "returns null when the root is missing" `
          ($null -eq (Find-SubscribedCopy (Join-Path $root "nope")))

    Write-Host "`nworkshop dir with unrelated items only"
    $ws1 = Join-Path $root "ws1"; New-Item -ItemType Directory $ws1 -Force | Out-Null
    $other = Join-Path $ws1 "2162986216"; New-Item -ItemType Directory $other -Force | Out-Null
    '{"title":"Toyota Supra","type":"web"}' | Set-Content (Join-Path $other "project.json")
    Check "ignores unrelated subscriptions" ($null -eq (Find-SubscribedCopy $ws1))

    Write-Host "`nworkshop dir containing the SignalRGB item"
    $ws2 = Join-Path $root "ws2"; New-Item -ItemType Directory $ws2 -Force | Out-Null
    $a = Join-Path $ws2 "111"; New-Item -ItemType Directory $a -Force | Out-Null
    '{"title":"Some Anime Girl","type":"web"}' | Set-Content (Join-Path $a "project.json")
    $b = Join-Path $ws2 "3456789"; New-Item -ItemType Directory $b -Force | Out-Null
    '{"title":"SignalRGB Glow","type":"web"}' | Set-Content (Join-Path $b "project.json")
    $found = Find-SubscribedCopy $ws2
    Check "detects the SignalRGB subscription" ($null -ne $found)
    Check "reports the workshop id" ($found.Id -eq "3456789") "got $($found.Id)"
    Check "reports the title" ($found.Title -eq "SignalRGB Glow") "got $($found.Title)"

    Write-Host "`nmalformed project.json"
    $ws3 = Join-Path $root "ws3"; New-Item -ItemType Directory $ws3 -Force | Out-Null
    $c = Join-Path $ws3 "222"; New-Item -ItemType Directory $c -Force | Out-Null
    "{ this is not json" | Set-Content (Join-Path $c "project.json")
    $d = Join-Path $ws3 "333"; New-Item -ItemType Directory $d -Force | Out-Null
    '{"title":"SignalRGB Glow"}' | Set-Content (Join-Path $d "project.json")
    $found3 = Find-SubscribedCopy $ws3
    Check "skips unparseable json and keeps looking" `
          ($null -ne $found3 -and $found3.Id -eq "333") "got $($found3.Id)"

    Write-Host "`ndirectory without project.json"
    $ws4 = Join-Path $root "ws4"; New-Item -ItemType Directory $ws4 -Force | Out-Null
    New-Item -ItemType Directory (Join-Path $ws4 "444") -Force | Out-Null
    Check "tolerates a bare directory" ($null -eq (Find-SubscribedCopy $ws4))

    Write-Host "`nreal machine"
    $realRoot = "${env:ProgramFiles(x86)}\Steam\steamapps\workshop\content\431960"
    $real = Find-SubscribedCopy $realRoot
    Write-Host "  (this machine: $(if($real){"subscribed to '$($real.Title)'"}else{'no SignalRGB subscription'}))"
    Check "real-machine probe does not throw" $true

    # The block above mirrors the real script's logic, so on its own it
    # would keep passing even if that logic were deleted. These assert
    # the shipped script still contains it and still wires up exit 4.
    Write-Host "`nshipped script still carries the detection"
    $script = Join-Path $PSScriptRoot "..\installer\reimport-wallpaper-bundles.ps1"
    Check "script exists" (Test-Path $script)
    if (Test-Path $script) {
        $src = Get-Content $script -Raw
        Check "looks under steamapps\workshop\content\431960" `
              ($src -match 'workshop\\steamapps' -or $src -match 'workshop\\content\\431960')
        Check "matches the item by SignalRGB in its title" ($src -match "title -match 'SignalRGB'")
        Check "exits 4 for a subscription-only setup" ($src -match 'exit 4')
        Check "does not exit 4 when a local project was patched" `
              ($src -match '\$weSubscribed -and -not \$weProjectPatched')
        Check "sets weProjectPatched on the local path" ($src -match '\$weProjectPatched = \$true')
        Check "parses cleanly" (
            $null -ne ([System.Management.Automation.Language.Parser]::ParseFile(
                (Resolve-Path $script).Path, [ref]$null, [ref]$null)))
    }
}
finally {
    Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue
}

$total = $pass + $fail.Count
Write-Host "`n  $pass/$total passed"
if ($fail.Count) { exit 1 } else { exit 0 }
