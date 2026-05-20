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
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german";  MessagesFile: "compiler:Languages\German.isl"

[Tasks]
; ── Wallpaper host: pick one or both. Each gates its own file copy,
;    Start-menu shortcut, and end-of-install "Open folder" action so the
;    user never sees a Lively prompt if they only picked WE (and vice versa).
Name: "installlively"; \
  Description: "Lively Wallpaper (free, recommended)"; \
  GroupDescription: "Wallpaper host:"; Flags: checkedonce
Name: "installlively/autoimport"; \
  Description: "Auto-import into Lively (skip the manual drag-and-drop step)"; \
  GroupDescription: "Wallpaper host:"; Flags: checkedonce
Name: "installwallpaperengine"; \
  Description: "Wallpaper Engine (Steam — auto-skipped if not detected)"; \
  GroupDescription: "Wallpaper host:"; Flags: unchecked
; ── Additional setup
Name: "installplugin"; \
  Description: "Install the SignalRGB Desktop Wallpaper plugin into the WhirlwindFX Plugins folder"; \
  GroupDescription: "Additional setup:"; Flags: checkedonce
Name: "autostart"; \
  Description: "Start bridge automatically on logon"; \
  GroupDescription: "Additional setup:"; Flags: checkedonce

[Files]
; Bridge + tray
Source: "..\wallpaper_bridge\dist_bridge\SignalRGBBridge.exe"; DestDir: "{app}"; Flags: ignoreversion

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
; ── WE-path: if Wallpaper Engine was detected we already dropped the
;    bundle into its projects folder — just nudge the user to open WE
;    and assign 'SignalRGB Glow' to each monitor (with a different
;    'Screen index' per assignment in the WE properties panel).
Filename: "{code:GetWallpaperEngineProjects}"; Verb: open; \
  Description: "Open the Wallpaper Engine projects folder (assign 'SignalRGB Glow' per monitor, pick a different Screen index each time)"; \
  Flags: postinstall skipifsilent shellexec nowait; \
  Tasks: installwallpaperengine; Check: WallpaperEngineDetected
; ── WE-path fallback: if Steam wasn't found, point them at our local
;    staging folder so they can drag the folder into WE manually.
Filename: "{app}\Wallpaper Engine wallpapers"; Verb: open; \
  Description: "Open the Wallpaper Engine bundle folder (drag 'signalrgb-glow' into Wallpaper Engine manually)"; \
  Flags: postinstall skipifsilent shellexec nowait; \
  Tasks: installwallpaperengine; Check: WallpaperEngineNotDetected
; ── Start the bridge right away (only if user kept autostart)
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Start the SignalRGB Wallpaper Bridge now"; \
  Flags: postinstall skipifsilent nowait; Tasks: autostart

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
// The MSIX (Microsoft Store) build hides it inside the sandboxed package
//   %LOCALAPPDATA%\Packages\rocksdanister.LivelyWallpaper_*\LocalState\Library\wallpapers
// We probe both, GitHub build first because that's what we recommend.
//
// Cached on first call so the per-file [Files] checks don't re-probe the
// disk hundreds of times during install.
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
  // 2. MSIX build — walk Packages\rocksdanister.LivelyWallpaper_* matches
  if FindFirst(AddBackslash(LocalApp) + 'Packages\rocksdanister.LivelyWallpaper_*', FR) then begin
    try
      repeat
        if (FR.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then begin
          if (FR.Name <> '.') and (FR.Name <> '..') then begin
            CandidateBase := AddBackslash(LocalApp) + 'Packages\' + FR.Name + '\LocalState';
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
