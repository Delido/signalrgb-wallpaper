# Release + winget tooling: the decisions that are easy to get subtly
# wrong and hard to notice afterwards.
#
# Both scripts under test have a history of exactly that:
#   * winget-publish.ps1 passed |machine to wingetcreate to set the
#     install scope. It never worked — every release since v2.2.1
#     shipped Scope: user while the installer required admin.
#   * release.ps1's first draft printed "re-import your bundle" on
#     bridge-only releases, because the condition treated every
#     prerelease as a wallpaper change.
#
# Neither would fail loudly. Hence these.

$ErrorActionPreference = "Stop"
$pass = 0; $fail = @()

function Check($label, $cond, $detail = "") {
    if ($cond) { $script:pass++; Write-Host "  PASS  $label" }
    else { $script:fail += $label; Write-Host "  FAIL  $label$(if($detail){" - $detail"})" }
}

$repo    = Resolve-Path (Join-Path $PSScriptRoot "..")
$release = Join-Path $repo "installer\release.ps1"
$winget  = Join-Path $repo "installer\winget-publish.ps1"

Write-Host "`nscripts parse under this PowerShell"
foreach ($f in @($release, $winget)) {
    $errs = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$null, [ref]$errs)
    Check "$([IO.Path]::GetFileName($f)) parses" (-not $errs) `
          ($(if ($errs) { $errs[0].Message } else { "" }))
}

Write-Host "`nno PowerShell 7-only syntax (installer scripts must run on 5.1)"
foreach ($f in @($release, $winget)) {
    $src = Get-Content $f -Raw
    $name = [IO.Path]::GetFileName($f)
    # ?. and ?? are 7-only and are parse errors on 5.1, which would take
    # the whole script down rather than degrade.
    Check "$name has no null-conditional operator" ($src -notmatch '\)\?\.')
    Check "$name has no null-coalescing operator" ($src -notmatch '\?\?')
}

Write-Host "`nrelease.ps1 — prerelease detection"
& {
    $src = Get-Content $release -Raw
    Check "detects -beta/-rc/-alpha as prerelease" ($src -match "isPrerelease = .*-\(beta\|rc\|alpha\)")
    Check "prereleases publish with --prerelease" ($src -match '"--prerelease"')
    Check "stable publishes with --latest" ($src -match '"--latest"')
    Check "prerelease skips winget" ($src -match 'skipped \(prerelease\)')
}

Write-Host "`nrelease.ps1 — wallpaper-change notice targets the right releases"
& {
    $src = Get-Content $release -Raw
    Check "strips the prerelease suffix before comparing" ($src -match "baseVersion = \(\`$version -split '-'\)\[0\]")
    Check "notice keys off WALLPAPER_VERSION vs base version" `
          ($src -match '\$wallpaperVersion -eq \$baseVersion')
    Check "does not treat every prerelease as a wallpaper change" `
          ($src -notmatch '\$wallpaperVersion -eq \$version -or \$isPrerelease')
    Check "says so explicitly on bridge-only releases" ($src -match 'Bridge-only release')

    # The comparison itself, exercised rather than grepped.
    function Test-NeedsReimport($appVer, $wpVer) {
        return (($appVer -split '-')[0]) -eq $wpVer
    }
    Check "2.4.3-beta.1 + wallpaper 2.4.2 -> no notice" `
          (-not (Test-NeedsReimport "2.4.3-beta.1" "2.4.2"))
    Check "2.4.2 + wallpaper 2.4.2 -> notice" `
          (Test-NeedsReimport "2.4.2" "2.4.2")
    Check "2.4.4-beta.1 + wallpaper 2.4.4 -> notice" `
          (Test-NeedsReimport "2.4.4-beta.1" "2.4.4")
    Check "2.5.0 + wallpaper 2.4.2 -> no notice" `
          (-not (Test-NeedsReimport "2.5.0" "2.4.2"))
}

Write-Host "`nrelease.ps1 — preflight refuses bad cuts"
& {
    $src = Get-Content $release -Raw
    Check "requires a RELEASE_NOTES entry" ($src -match 'No RELEASE_NOTES entry for')
    Check "requires a CHANGELOG heading" ($src -match 'No .* heading in CHANGELOG')
    Check "refuses a dirty tree by default" ($src -match 'Working tree is dirty')
    Check "refuses an existing tag" ($src -match 'already exists')
    Check "refuses on failing tests" ($src -match 'refusing to cut a release')
    Check "notes come from RELEASE_NOTES, not hand-written" ($src -match "RELEASE_NOTES.get")
}

Write-Host "`nwinget-publish.ps1 — scope is patched, not merely requested"
& {
    $src = Get-Content $winget -Raw
    Check "patches Scope: machine into the generated YAML" `
          ($src -match "'Scope: machine'")
    Check "adds ElevationRequirement" ($src -match 'ElevationRequirement: elevationRequired')
    Check "verifies the patch before submitting" `
          ($src -match 'refusing to submit')
    Check "generates and submits as separate steps" `
          ($src -match '"submit"' -and $src -match '"update"')
    Check "validates the manifest before submit" ($src -match 'winget validate')
    Check "still refuses prerelease tags" ($src -match 'Refusing to publish a prerelease')
}

Write-Host "`nwinget-publish.ps1 — fork sync"
& {
    $src = Get-Content $winget -Raw
    Check "syncs the fork with upstream" ($src -match 'repo sync')
    Check "targets microsoft/winget-pkgs" ($src -match 'microsoft/winget-pkgs')
    Check "a sync failure does not abort the submit" ($src -match 'submitting anyway')
    Check "falls back to well-known gh.exe locations" ($src -match 'GitHub CLI\\\\gh\.exe|GitHub CLI\\gh\.exe')
}

$total = $pass + $fail.Count
Write-Host "`n  $pass/$total passed"
if ($fail.Count) { exit 1 } else { exit 0 }
