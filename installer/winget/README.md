# Winget manifest scaffolding

Manifest files for submitting **SignalRGB Desktop Wallpaper** to the
[microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs)
community repository. Once accepted, users can install with:

```powershell
winget install Delido.SignalRGBWallpaper
```

## Files

- `Delido.SignalRGBWallpaper.yaml` — top-level version manifest
- `Delido.SignalRGBWallpaper.installer.yaml` — installer details + SHA256
- `Delido.SignalRGBWallpaper.locale.en-US.yaml` — English metadata
  (description, tags, URLs)

Three-file v1.6 manifest format, the current Winget standard.

## Per-release update workflow

1. Build the new installer via `pwsh installer/build.ps1`.
2. Compute SHA256 of the new exe:

   ```powershell
   Get-FileHash installer_out\SignalRGBWallpaperSetup-<ver>-beta.exe `
     -Algorithm SHA256
   ```

3. In all three manifest files, bump `PackageVersion` to match the new
   tag (`0.9.21-beta` style).
4. In `*.installer.yaml`, update the `InstallerUrl` and
   `InstallerSha256` fields to the new release asset.
5. Submit via `wingetcreate submit` (preferred) or by opening a PR
   directly against `microsoft/winget-pkgs`:

   ```powershell
   wingetcreate submit installer/winget/
   ```

   `wingetcreate` runs `winget validate` first and surfaces any schema
   errors before opening the PR.

## Approval flow

Winget moderators usually approve community submissions within
1-3 days for prerelease (`-beta`) tags. Stable releases (without
the `-beta` suffix) get prioritised but we don't ship those yet.

## Status

Initial scaffolding shipped v0.9.21-beta. **Not yet submitted** to
`microsoft/winget-pkgs` — first submission still on the maintainer's
todo list. Once submitted + accepted, only step 5 of the workflow
needs running per release.
