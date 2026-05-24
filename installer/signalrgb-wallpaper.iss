; SignalRGB Desktop Wallpaper — Inno Setup installer.
;
; Per-user install (no admin needed). Installs:
;   {app}                                  -- LOCALAPPDATA\Programs\SignalRGBWallpaper
;     ├ SignalRGBBridge.exe                -- bridge + tray
;     ├ Lively wallpapers\Screen{1,2,3,4}.zip
;     ├ Wallpaper Engine wallpapers\signalrgb-glow\
;     ├ LICENSE, README.md, CHANGELOG.md
;   {userdocs}\WhirlwindFX\Plugins         -- SignalRGB plugin (.js + .qml)
;   HKCU\...\Run\SignalRGBWallpaperBridge  -- optional autostart
;
; Compile with:
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /DMyAppVersion=0.4.0 installer\signalrgb-wallpaper.iss
; (build.ps1 wraps this with version + dependency build steps.)

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName     "SignalRGB Desktop Wallpaper"
#define MyAppPublisher "Delido"
#define MyAppURL      "https://github.com/Delido/signalrgb-wallpaper"
#define MyAppExeName  "SignalRGBBridge.exe"

[Setup]
; AppId locks the install across upgrades — keep this GUID stable forever.
AppId={{A2F6E3C8-7B91-4D3A-9C5F-1E6A0B8D2F71}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\SignalRGBWallpaper
DefaultGroupName=SignalRGB Wallpaper
DisableProgramGroupPage=yes
DisableDirPage=auto
LicenseFile=..\LICENSE
OutputDir=..\installer_out
OutputBaseFilename=SignalRGBWallpaperSetup-{#MyAppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\SignalRGBBridge.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; `force` (not `yes`) is critical for the tray's silent
; auto-update path: `yes` prompts the user to confirm closing the
; running bridge, and the prompt is suppressed by `/SUPPRESSMSGBOXES`,
; which deadlocks the installer. `force` closes running instances
; without prompting so the silent flow can replace SignalRGBBridge.exe.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german";  MessagesFile: "compiler:Languages\German.isl"

[Tasks]
; ── Wallpaper host: pick one or both. Each gates its own file copy,
;    Start-menu shortcut, and end-of-install "Open folder" action so the
;    user never sees a Lively prompt if they only picked WE (and vice
;    versa). WE defaults to checkedonce — detected users get auto-copy
;    out of the box; undetected users can still tick it but the [Files]
;    entries have `Check: WallpaperEngineDetected`, so nothing actually
;    happens unless Steam + WE exist on disk.
Name: "installlively"; \
  Description: "Lively Wallpaper (free, recommended)"; \
  GroupDescription: "Wallpaper host:"; Flags: checkedonce
Name: "installlively/autoimport"; \
  Description: "Auto-import into Lively's Library (skip the manual drag-and-drop step)"; \
  GroupDescription: "Wallpaper host:"; Flags: checkedonce
Name: "installlively/autoinstall"; \
  Description: "Auto-install Lively Wallpaper if not already present (downloads the latest release from GitHub)"; \
  GroupDescription: "Wallpaper host:"; Flags: unchecked
Name: "installwallpaperengine"; \
  Description: "Wallpaper Engine (Steam — auto-skipped if not detected)"; \
  GroupDescription: "Wallpaper host:"; Flags: checkedonce
; ── Additional setup
; installplugin lives at the TOP of the group on purpose: it's the
; piece that lets SignalRGB actually talk to the bridge. Without it
; the whole product does nothing — no glow, no live colours. Keep
; checkedonce (default on for first installs) AND mention "required"
; in the description so users don't casually uncheck it.
Name: "installplugin"; \
  Description: "Install the SignalRGB Desktop Wallpaper plugin (required — SignalRGB drives the bridge through this)"; \
  GroupDescription: "Additional setup:"; Flags: checkedonce
Name: "autostart"; \
  Description: "Start the bridge automatically on logon"; \
  GroupDescription: "Additional setup:"; Flags: checkedonce
Name: "openconfigurator"; \
  Description: "Open the Configurator in the browser when done"; \
  GroupDescription: "Additional setup:"; Flags: checkedonce

[Files]
; Bridge + tray
Source: "..\wallpaper_bridge\dist_bridge\SignalRGBBridge.exe"; DestDir: "{app}"; Flags: ignoreversion
; PS helper for the tray's "Re-import wallpaper bundles" entry — the
; bridge shells out to this script after locating it next to the exe.
Source: "reimport-wallpaper-bundles.ps1"; DestDir: "{app}"; Flags: ignoreversion

; SignalRGB plugin (only if user opted in)
Source: "..\SignalRGB_Desktop_Wallpaper.js";  DestDir: "{userdocs}\WhirlwindFX\Plugins"; \
  Flags: ignoreversion; Tasks: installplugin
Source: "..\SignalRGB_Desktop_Wallpaper.qml"; DestDir: "{userdocs}\WhirlwindFX\Plugins"; \
  Flags: ignoreversion; Tasks: installplugin

; Lively wallpaper zips — kept under {app} as a manual-import fallback,
; regardless of whether auto-import below runs.
Source: "..\wallpaper_bridge\SignalRGB_Glow_Screen1.zip"; DestDir: "{app}\Lively wallpapers"; \
  Flags: ignoreversion; Tasks: installlively
Source: "..\wallpaper_bridge\SignalRGB_Glow_Screen2.zip"; DestDir: "{app}\Lively wallpapers"; \
  Flags: ignoreversion; Tasks: installlively
Source: "..\wallpaper_bridge\SignalRGB_Glow_Screen3.zip"; DestDir: "{app}\Lively wallpapers"; \
  Flags: ignoreversion; Tasks: installlively
Source: "..\wallpaper_bridge\SignalRGB_Glow_Screen4.zip"; DestDir: "{app}\Lively wallpapers"; \
  Flags: ignoreversion; Tasks: installlively

; Direct auto-import into Lively's library — deterministic folder names so
; subsequent installer runs overwrite in place, killing the "delete +
; re-import after every update" caveat. Only fires when:
;   • the Lively task is checked, AND
;   • its sub-task "autoimport" is checked, AND
;   • a Lively install was detected (GitHub or MSIX build)
Source: "..\wallpaper_bridge\lively_bundles\signalrgb-glow-screen-1\*"; \
  DestDir: "{code:GetLivelyLibraryPath}\signalrgb-glow-screen-1"; \
  Flags: recursesubdirs createallsubdirs ignoreversion; \
  Tasks: installlively/autoimport; Check: LivelyDetected
Source: "..\wallpaper_bridge\lively_bundles\signalrgb-glow-screen-2\*"; \
  DestDir: "{code:GetLivelyLibraryPath}\signalrgb-glow-screen-2"; \
  Flags: recursesubdirs createallsubdirs ignoreversion; \
  Tasks: installlively/autoimport; Check: LivelyDetected
Source: "..\wallpaper_bridge\lively_bundles\signalrgb-glow-screen-3\*"; \
  DestDir: "{code:GetLivelyLibraryPath}\signalrgb-glow-screen-3"; \
  Flags: recursesubdirs createallsubdirs ignoreversion; \
  Tasks: installlively/autoimport; Check: LivelyDetected
Source: "..\wallpaper_bridge\lively_bundles\signalrgb-glow-screen-4\*"; \
  DestDir: "{code:GetLivelyLibraryPath}\signalrgb-glow-screen-4"; \
  Flags: recursesubdirs createallsubdirs ignoreversion; \
  Tasks: installlively/autoimport; Check: LivelyDetected

; Wallpaper Engine bundle — single combined item with a "Screen index"
; property the user picks per assignment. Replaces the four per-screen
; folders we used to ship: one Library tile assigned N times beats four
; tiles assigned once each. Two destinations:
;   (1) a manual-import staging folder under {app}\Wallpaper Engine
;       wallpapers\signalrgb-glow\, and
;   (2) — when Steam + Wallpaper Engine are detected — the live projects
;       folder Wallpaper Engine actually scans, so the wallpaper shows
;       up in "My Wallpapers" without the user touching anything.
Source: "..\wallpaper_bridge\we_bundles_single\signalrgb-glow\*"; \
  DestDir: "{app}\Wallpaper Engine wallpapers\signalrgb-glow"; \
  Flags: recursesubdirs createallsubdirs ignoreversion; Tasks: installwallpaperengine
Source: "..\wallpaper_bridge\we_bundles_single\signalrgb-glow\*"; \
  DestDir: "{code:GetWallpaperEngineProjects}\signalrgb-glow"; \
  Flags: recursesubdirs createallsubdirs ignoreversion; \
  Tasks: installwallpaperengine; Check: WallpaperEngineDetected

; Docs (so the user has a local copy)
Source: "..\LICENSE";      DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md";    DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion

; Lively bootstrapper script — extracted to {tmp} at install start so the
; CurStepChanged(ssInstall) hook can shell it out before [Files] runs.
; `dontcopy` keeps it out of the final {app} install dir; we just want it
; alongside the wizard for the duration of the install.
Source: "install_lively.ps1"; Flags: dontcopy

; Wallpaper library — procedurally generated by installer/generate_library.py,
; dropped into the user's %LOCALAPPDATA%\SignalRGBWallpaper\library so the
; Configurator's "Library" strip is non-empty on first launch. Bridge serves
; them via /library/list + /library/<file>. Users can add their own PNGs to
; this folder by hand; we don't overwrite anything except our generated set
; on upgrade.
;
; Split into two entries on purpose:
;   • PNGs: always copy on install/upgrade (matches the old behaviour and
;     restores starter wallpapers if the user accidentally deleted them).
;   • library.json: only on first install (`onlyifdoesntexist`). The bridge
;     regenerates this file from the directory contents on every startup
;     and on every upload/delete, so overwriting it loses per-entry
;     pinned/order state and hides user-uploaded PNGs until the next
;     upload triggers a rebuild.
Source: "..\wallpaper_bridge\library\*.png"; \
  DestDir: "{localappdata}\SignalRGBWallpaper\library"; \
  Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\wallpaper_bridge\library\library.json"; \
  DestDir: "{localappdata}\SignalRGBWallpaper\library"; \
  Flags: onlyifdoesntexist

[InstallDelete]
; Upgrade cleanup: builds before v0.7.2-beta shipped four per-screen WE
; folders (SignalRGB_Glow_Screen1..4). The combined "signalrgb-glow"
; bundle from step 3a replaces all four, so wipe the legacy folders
; from both destinations BEFORE the new [Files] copy runs. Gated on the
; WE task so we don't touch anything if the user opted out of WE.
; (The per-screen items were never published to Steam Workshop, so the
; installer is the only path that ever placed these folders.)
Type: filesandordirs; Name: "{app}\Wallpaper Engine wallpapers\SignalRGB_Glow_Screen1"; \
  Tasks: installwallpaperengine
Type: filesandordirs; Name: "{app}\Wallpaper Engine wallpapers\SignalRGB_Glow_Screen2"; \
  Tasks: installwallpaperengine
Type: filesandordirs; Name: "{app}\Wallpaper Engine wallpapers\SignalRGB_Glow_Screen3"; \
  Tasks: installwallpaperengine
Type: filesandordirs; Name: "{app}\Wallpaper Engine wallpapers\SignalRGB_Glow_Screen4"; \
  Tasks: installwallpaperengine
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen1"; \
  Tasks: installwallpaperengine; Check: WallpaperEngineDetected
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen2"; \
  Tasks: installwallpaperengine; Check: WallpaperEngineDetected
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen3"; \
  Tasks: installwallpaperengine; Check: WallpaperEngineDetected
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen4"; \
  Tasks: installwallpaperengine; Check: WallpaperEngineDetected

[Icons]
Name: "{group}\SignalRGB Wallpaper Bridge"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Lively wallpapers folder";   Filename: "{app}\Lively wallpapers"; \
  Tasks: installlively
Name: "{group}\Wallpaper Engine wallpapers folder"; Filename: "{app}\Wallpaper Engine wallpapers"; \
  Tasks: installwallpaperengine
Name: "{group}\Documentation (README)";     Filename: "{app}\README.md"
Name: "{group}\Uninstall SignalRGB Wallpaper"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "SignalRGBWallpaperBridge"; \
  ValueData: """{app}\{#MyAppExeName}"""; \
  Flags: uninsdeletevalue; Tasks: autostart

[Run]
; ── Lively-path: open the staging folder so the user can drag the zips
;    onto Lively. Only shown if (a) Lively was picked and (b) auto-import
;    did NOT already place the bundles in Lively's library — otherwise the
;    folder open is just clutter.
Filename: "{app}\Lively wallpapers"; Verb: open; \
  Description: "Open the Lively wallpapers folder (drag the zips onto Lively)"; \
  Flags: postinstall skipifsilent shellexec nowait; \
  Tasks: installlively; Check: NotLivelyAutoImported
; ── WE-path: when WE was detected, the bundle is already in WE's
;    projects folder and shows up in "My Wallpapers" on next start.
;    No post-install action is offered for the detected case — the
;    "Open projects folder" prompt the older betas had was just
;    filesystem-confirmation noise; the user opens WE, not Explorer.
;
; ── WE-path fallback: if Steam wasn't found, point them at our local
;    staging folder so they can drag the folder into WE manually.
Filename: "{app}\Wallpaper Engine wallpapers"; Verb: open; \
  Description: "Open the Wallpaper Engine bundle folder (drag 'signalrgb-glow' into Wallpaper Engine manually)"; \
  Flags: postinstall skipifsilent shellexec nowait; \
  Tasks: installwallpaperengine; Check: WallpaperEngineNotDetected
; ── Start the bridge right away (only if user kept autostart). Dropping
;    `skipifsilent` means in silent mode (used by the tray's
;    "Download + install update" flow) the bridge auto-restarts after
;    the new exe is in place. In interactive mode the `postinstall`
;    checkbox still gates this on user opt-in.
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Start the SignalRGB Wallpaper Bridge now"; \
  Flags: postinstall nowait; Tasks: autostart
; ── Configurator: open the in-browser settings UI so the user can pick
;    a wallpaper from the bundled Library, set up screens, etc., right
;    after install. Gated on the new openconfigurator task.
Filename: "http://127.0.0.1:17320/configurator"; \
  Description: "Open the Configurator in your browser"; \
  Flags: postinstall skipifsilent shellexec nowait; Tasks: openconfigurator

[UninstallDelete]
; Clean the Steam-side WE bundle if we copied it there. Removes only the
; single combined folder we install; leaves any other WE wallpapers alone.
; Legacy entries below catch pre-v0.7.2-beta installs that shipped four
; per-screen folders, so an upgrade-uninstall still cleans those up.
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\signalrgb-glow"
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen1"
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen2"
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen3"
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen4"
; Clean the auto-imported Lively bundles. Deterministic folder names mean
; we know exactly which subfolders belong to us — Lively's other wallpapers
; under the same Library\wallpapers\ tree are left alone.
Type: filesandordirs; Name: "{code:GetLivelyLibraryPath}\signalrgb-glow-screen-1"
Type: filesandordirs; Name: "{code:GetLivelyLibraryPath}\signalrgb-glow-screen-2"
Type: filesandordirs; Name: "{code:GetLivelyLibraryPath}\signalrgb-glow-screen-3"
Type: filesandordirs; Name: "{code:GetLivelyLibraryPath}\signalrgb-glow-screen-4"

[UninstallRun]
; Make sure the running bridge releases its file handles before uninstall
; tries to delete the exe.
Filename: "{cmd}"; Parameters: "/c taskkill /f /im SignalRGBBridge.exe"; \
  Flags: runhidden; RunOnceId: "KillBridge"

[Code]
// ─────────────────────────────────────────────────────────────────────────────
// Wallpaper Engine detection.
//
// Strategy:
//   1. Read HKCU\Software\Valve\Steam → SteamPath. That's the install dir of
//      the Steam client itself, not necessarily where libraries live.
//   2. Check <SteamPath>\steamapps\common\wallpaper_engine\projects\myprojects
//      — covers users who only ever installed Steam games to the default
//      drive.
//   3. If not there, parse <SteamPath>\steamapps\libraryfolders.vdf, which
//      lists every Steam library Steam knows about (one per drive). Try each
//      in turn for the wallpaper_engine subfolder.
//
// All paths are returned with forward slashes intentionally avoided — Inno
// Setup's path helpers want backslashes on Windows.
// ─────────────────────────────────────────────────────────────────────────────

function NormaliseSlashes(S: String): String;
var
  I: Integer;
begin
  Result := S;
  for I := 1 to Length(Result) do
    if Result[I] = '/' then Result[I] := '\';
end;

function TryWePath(Base: String): String;
var
  Candidate: String;
begin
  Result := '';
  if Base = '' then exit;
  Candidate := AddBackslash(Base) + 'steamapps\common\wallpaper_engine';
  if DirExists(Candidate) then
    Result := AddBackslash(Candidate) + 'projects\myprojects';
end;

function ParseLibraryFolders(SteamPath: String): TStringList;
var
  Vdf: String;
  Lines: TStringList;
  I, Q: Integer;
  Line, Rest, Path: String;
begin
  Result := TStringList.Create;
  Vdf := AddBackslash(SteamPath) + 'steamapps\libraryfolders.vdf';
  if not FileExists(Vdf) then exit;
  Lines := TStringList.Create;
  try
    Lines.LoadFromFile(Vdf);
    for I := 0 to Lines.Count - 1 do begin
      Line := Lines[I];
      // We're looking for lines like:    "path"      "E:\\SteamLibrary"
      // PascalScript has no PosEx, so we slice the line forward step by
      // step with Copy + Pos.
      if Pos('"path"', Line) = 0 then continue;
      Rest := Copy(Line, Pos('"path"', Line) + 6, Length(Line));
      // Skip whitespace, find the opening quote of the value.
      Q := Pos('"', Rest);
      if Q = 0 then continue;
      Rest := Copy(Rest, Q + 1, Length(Rest));
      // Closing quote.
      Q := Pos('"', Rest);
      if Q = 0 then continue;
      Path := Copy(Rest, 1, Q - 1);
      // VDF escapes backslashes as \\ — un-escape so DirExists works.
      StringChange(Path, '\\', '\');
      if Path <> '' then Result.Add(Path);
    end;
  finally
    Lines.Free;
  end;
end;

var
  CachedWePath: String;
  CachedWePathInitialised: Boolean;

function GetWallpaperEngineProjects(Param: String): String;
var
  SteamPath: String;
  WePath: String;
  Libraries: TStringList;
  I: Integer;
begin
  if CachedWePathInitialised then begin
    Result := CachedWePath;
    exit;
  end;
  Result := '';
  if not RegQueryStringValue(HKCU, 'Software\Valve\Steam', 'SteamPath', SteamPath) then begin
    CachedWePath := '';
    CachedWePathInitialised := True;
    exit;
  end;
  SteamPath := NormaliseSlashes(SteamPath);
  // First try the default library (under Steam install itself)
  WePath := TryWePath(SteamPath);
  if WePath <> '' then begin
    Result := WePath;
    CachedWePath := WePath;
    CachedWePathInitialised := True;
    exit;
  end;
  // Then walk the rest from libraryfolders.vdf
  Libraries := ParseLibraryFolders(SteamPath);
  try
    for I := 0 to Libraries.Count - 1 do begin
      WePath := TryWePath(Libraries[I]);
      if WePath <> '' then begin
        Result := WePath;
        Break;
      end;
    end;
  finally
    Libraries.Free;
  end;
  CachedWePath := Result;
  CachedWePathInitialised := True;
end;

function WallpaperEngineDetected(): Boolean;
begin
  Result := (GetWallpaperEngineProjects('') <> '');
end;

function WallpaperEngineNotDetected(): Boolean;
begin
  Result := (GetWallpaperEngineProjects('') = '');
end;

// ─────────────────────────────────────────────────────────────────────────────
// Lively Wallpaper detection.
//
// GitHub-installer build keeps its library under
//   %LOCALAPPDATA%\Lively Wallpaper\Library\wallpapers
// The MSIX (Microsoft Store) build runs inside an AppContainer sandbox.
// When the MSIX-packaged Lively writes to `%LOCALAPPDATA%\Lively Wallpaper\`
// in its own code, Windows transparently redirects to
//   %LOCALAPPDATA%\Packages\rocksdanister.LivelyWallpaper_*\LocalCache\Local\Lively Wallpaper\
// — NOT to LocalState. Earlier versions of this installer probed
// LocalState (where some MSIX apps explicitly store data), missed
// the LocalCache redirection target, and silently shipped wallpapers
// into a folder Lively was never going to read from.
//
// Probe order:
//   1. GitHub-installer build (LocalAppData direct)
//   2. MSIX LocalCache (redirection target — the one MSIX Lively
//      actually reads)
//   3. MSIX LocalState (kept as a fall-back for any Lively build
//      that did target LocalState explicitly)
//
// Cached on first call so the per-file [Files] checks don't re-probe
// the disk hundreds of times during install.
// ─────────────────────────────────────────────────────────────────────────────

var
  CachedLivelyPath: String;
  CachedLivelyPathInitialised: Boolean;

function TryLivelyPath(Base: String): String;
begin
  Result := '';
  if Base = '' then exit;
  if DirExists(Base) then begin
    // Library subfolder may not exist yet on a fresh Lively install, but
    // ForceDirectories will create it; Lively scans this folder on startup.
    Result := AddBackslash(Base) + 'Library\wallpapers';
    if not DirExists(Result) then ForceDirectories(Result);
  end;
end;

function GetLivelyLibraryPath(Param: String): String;
var
  LocalApp: String;
  FR: TFindRec;
  PackageDir: String;
  CandidateBase: String;
  CandidatePath: String;
begin
  if CachedLivelyPathInitialised then begin
    Result := CachedLivelyPath;
    exit;
  end;
  Result := '';
  LocalApp := ExpandConstant('{localappdata}');
  // 1. GitHub-installer build
  CandidateBase := AddBackslash(LocalApp) + 'Lively Wallpaper';
  CandidatePath := TryLivelyPath(CandidateBase);
  if CandidatePath <> '' then begin
    Result := CandidatePath;
    CachedLivelyPath := Result;
    CachedLivelyPathInitialised := True;
    exit;
  end;
  // 2 + 3. MSIX build — walk Packages\rocksdanister.LivelyWallpaper_*
  // matches and try LocalCache first (the redirection target the
  // sandboxed app actually reads), then LocalState.
  if FindFirst(AddBackslash(LocalApp) + 'Packages\rocksdanister.LivelyWallpaper_*', FR) then begin
    try
      repeat
        if (FR.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then begin
          if (FR.Name <> '.') and (FR.Name <> '..') then begin
            PackageDir := AddBackslash(LocalApp) + 'Packages\' + FR.Name;
            // 2. LocalCache — Windows redirection target for legacy
            //    %LOCALAPPDATA%\Lively Wallpaper\ writes
            CandidateBase := AddBackslash(PackageDir) + 'LocalCache\Local\Lively Wallpaper';
            CandidatePath := TryLivelyPath(CandidateBase);
            if CandidatePath <> '' then begin
              Result := CandidatePath;
              Break;
            end;
            // 3. LocalState — explicit app-data location (some Lively
            //    builds may target this directly).
            CandidateBase := AddBackslash(PackageDir) + 'LocalState';
            CandidatePath := TryLivelyPath(CandidateBase);
            if CandidatePath <> '' then begin
              Result := CandidatePath;
              Break;
            end;
          end;
        end;
      until not FindNext(FR);
    finally
      FindClose(FR);
    end;
  end;
  CachedLivelyPath := Result;
  CachedLivelyPathInitialised := True;
end;

function LivelyDetected(): Boolean;
begin
  Result := (GetLivelyLibraryPath('') <> '');
end;

function NotLivelyAutoImported(): Boolean;
begin
  // True when the user opted out of auto-import OR Lively wasn't detected.
  // In that case we still want to point them at the staging folder so they
  // can drag the zips by hand.
  Result := not (IsTaskSelected('installlively/autoimport') and LivelyDetected());
end;

// ─────────────────────────────────────────────────────────────────────────────
// Auto-Lively bootstrapper.
//
// When the user kept the `installlively/autoinstall` task AND no Lively
// install was detected on disk, we shell out to install_lively.ps1 — a
// small PowerShell script bundled into the wizard via [Files]
// `dontcopy`. The script queries GitHub Releases for the latest Lively
// build, downloads its setup exe, and runs it silently
// (/VERYSILENT /SUPPRESSMSGBOXES /NORESTART).
//
// We do this in CurStepChanged(ssInstall) — BEFORE the main [Files]
// pass — so when the auto-import entries (Check: LivelyDetected) run a
// moment later, they see the freshly-installed Lively library. The
// cached `CachedLivelyPathInitialised` flag is reset before the check
// so the new install is picked up.
//
// If the script fails (network down, GitHub asset missing, silent
// install rejected) we don't kill the wizard — the user can finish
// installing the bridge + plugin without Lively, then install Lively
// manually later.
// ─────────────────────────────────────────────────────────────────────────────

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  ScriptPath: String;
begin
  if CurStep = ssInstall then begin
    if IsTaskSelected('installlively/autoinstall') and (not LivelyDetected()) then begin
      ExtractTemporaryFile('install_lively.ps1');
      ScriptPath := ExpandConstant('{tmp}\install_lively.ps1');
      WizardForm.StatusLabel.Caption := 'Downloading + installing Lively Wallpaper…';
      Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
           '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '"',
           '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      // Force re-detection so the auto-import [Files] entries see the
      // fresh install path. If the script failed, LivelyDetected() will
      // still return False and the auto-import entries no-op via their
      // Check.
      CachedLivelyPathInitialised := False;
    end;
  end;
end;
