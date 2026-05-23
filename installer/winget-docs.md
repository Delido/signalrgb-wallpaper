# Winget submission workflow

Manifest files for submitting **SignalRGB Desktop Wallpaper** to the
[microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs)
community repository. Once accepted, users can install with:

```powershell
winget install Delido.SignalRGBWallpaper
```

This file lives outside `installer/winget/` on purpose — `winget validate`
treats every file inside the manifest folder as YAML, so a `README.md`
in there breaks validation with a confusing
`mapping values are not allowed in this context` error on line 5
(which turns out to be the first line of the markdown body, parsed
as YAML and tripping on the trailing colon after "install with").

## Files in `installer/winget/`

- `Delido.SignalRGBWallpaper.yaml` — top-level version manifest
- `Delido.SignalRGBWallpaper.installer.yaml` — installer URL + SHA256
- `Delido.SignalRGBWallpaper.locale.en-US.yaml` — English metadata
  (description, tags, URLs)

Three-file v1.6 manifest format, the current Winget standard. Pure YAML,
no comment headers — Winget's parser is fragile about non-YAML content
mixed in.

## Per-release update workflow

1. Build the new installer via `pwsh installer/build.ps1`.
2. Compute SHA256 of the new exe:

   ```powershell
   (Get-FileHash installer_out\SignalRGBWallpaperSetup-<ver>-beta.exe `
       -Algorithm SHA256).Hash
   ```

3. In all three manifest files, bump `PackageVersion` to match the new
   tag (e.g. `0.9.22-beta`).
4. In `*.installer.yaml`, update the `InstallerUrl` and
   `InstallerSha256` fields to the new release asset.
5. Submit via `wingetcreate`. The token comes from the already-authed
   `gh` CLI so no separate PAT is needed:

   ```powershell
   wingetcreate submit `
     --token (gh auth token) `
     --no-open `
     --prtitle "Update Delido.SignalRGBWallpaper to <ver>" `
     installer/winget
   ```

   `wingetcreate` runs `winget validate` first and surfaces any schema
   errors before opening the PR upstream.

## Approval flow

Winget moderators usually approve community submissions within 1-3 days.
Watch the PR for automated checks (`Azure-Pipelines` validation) and any
moderator comments. If a check fails, fix locally, force-push, and the
checks re-run automatically.

## Status

- ✅ Initial submission opened **2026-05-23** as
  [winget-pkgs PR #378672](https://github.com/microsoft/winget-pkgs/pull/378672)
  for v0.9.21-beta.
- 🔲 Per-release submissions still need running by hand. Worth
  automating into `installer/build.ps1` once the first one merges.

## Known fragility

- The manifest folder must contain ONLY the three `.yaml` files. Any
  `.md` / `.txt` / `.json` in the same dir will be parsed as YAML by
  `winget validate` and fail.
- Comment headers inside the YAML files (`# yaml-language-server:` etc.)
  also trip the parser in some cases. Keep the manifests bare.
- `wingetcreate --token` logs a warning that the token may end up in
  logs; in our scripted use that's tolerable since the token comes
  from `gh auth token` (revocable + already cached locally).
