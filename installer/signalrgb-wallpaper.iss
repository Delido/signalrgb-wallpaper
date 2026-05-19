; SignalRGB Desktop Wallpaper — Inno Setup installer.
;
; Per-user install (no admin needed). Installs:
;   {app}                                  -- LOCALAPPDATA\Programs\SignalRGBWallpaper
;     ├ SignalRGBBridge.exe                -- bridge + tray
;     ├ Lively wallpapers\Screen{1,2,3}.zip
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

; Lively wallpaper zips — only copied if the Lively task is selected.
; User drags them into Lively after install (the post-install action
; opens the folder).
Source: "..\wallpaper_bridge\SignalRGB_Glow_Screen1.zip"; DestDir: "{app}\Lively wallpapers"; \
  Flags: ignoreversion; Tasks: installlively
Source: "..\wallpaper_bridge\SignalRGB_Glow_Screen2.zip"; DestDir: "{app}\Lively wallpapers"; \
  Flags: ignoreversion; Tasks: installlively
Source: "..\wallpaper_bridge\SignalRGB_Glow_Screen3.zip"; DestDir: "{app}\Lively wallpapers"; \
  Flags: ignoreversion; Tasks: installlively

; Wallpaper Engine bundles — only copied if the WE task is selected.
; Two destinations: (1) a manual-import staging folder under {app}, and
; (2) — when Steam + Wallpaper Engine are detected — the live projects
; folder Wallpaper Engine actually scans, so the wallpapers show up in
; "My Wallpapers" without the user touching anything.
Source: "..\wallpaper_bridge\we_bundles\SignalRGB_Glow_Screen1\*"; \
  DestDir: "{app}\Wallpaper Engine wallpapers\SignalRGB_Glow_Screen1"; \
  Flags: recursesubdirs createallsubdirs ignoreversion; Tasks: installwallpaperengine
Source: "..\wallpaper_bridge\we_bundles\SignalRGB_Glow_Screen2\*"; \
  DestDir: "{app}\Wallpaper Engine wallpapers\SignalRGB_Glow_Screen2"; \
  Flags: recursesubdirs createallsubdirs ignoreversion; Tasks: installwallpaperengine
Source: "..\wallpaper_bridge\we_bundles\SignalRGB_Glow_Screen3\*"; \
  DestDir: "{app}\Wallpaper Engine wallpapers\SignalRGB_Glow_Screen3"; \
  Flags: recursesubdirs createallsubdirs ignoreversion; Tasks: installwallpaperengine
Source: "..\wallpaper_bridge\we_bundles\SignalRGB_Glow_Screen1\*"; \
  DestDir: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen1"; \
  Flags: recursesubdirs createallsubdirs ignoreversion; \
  Tasks: installwallpaperengine; Check: WallpaperEngineDetected
Source: "..\wallpaper_bridge\we_bundles\SignalRGB_Glow_Screen2\*"; \
  DestDir: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen2"; \
  Flags: recursesubdirs createallsubdirs ignoreversion; \
  Tasks: installwallpaperengine; Check: WallpaperEngineDetected
Source: "..\wallpaper_bridge\we_bundles\SignalRGB_Glow_Screen3\*"; \
  DestDir: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen3"; \
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
;    onto Lively. Only shown if they picked Lively.
Filename: "{app}\Lively wallpapers"; Verb: open; \
  Description: "Open the Lively wallpapers folder (drag the zips onto Lively)"; \
  Flags: postinstall skipifsilent shellexec nowait; Tasks: installlively
; ── WE-path: if Wallpaper Engine was detected we already dropped the
;    bundles into its projects folder — just nudge the user to open WE
;    and pick them from "My Wallpapers". (Open the WE projects folder so
;    they can visually confirm.)
Filename: "{code:GetWallpaperEngineProjects}"; Verb: open; \
  Description: "Open the Wallpaper Engine projects folder (wallpapers are already there — assign per monitor in WE)"; \
  Flags: postinstall skipifsilent shellexec nowait; \
  Tasks: installwallpaperengine; Check: WallpaperEngineDetected
; ── WE-path fallback: if Steam wasn't found, point them at our local
;    staging folder so they can drag the folders to WE manually.
Filename: "{app}\Wallpaper Engine wallpapers"; Verb: open; \
  Description: "Open the Wallpaper Engine bundles folder (drag the folders into Wallpaper Engine manually)"; \
  Flags: postinstall skipifsilent shellexec nowait; \
  Tasks: installwallpaperengine; Check: WallpaperEngineNotDetected
; ── Start the bridge right away (only if user kept autostart)
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Start the SignalRGB Wallpaper Bridge now"; \
  Flags: postinstall skipifsilent nowait; Tasks: autostart

[UninstallDelete]
; Clean the Steam-side WE bundles if we copied them there. Removes only our
; three folders; leaves any other WE wallpapers alone.
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen1"
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen2"
Type: filesandordirs; Name: "{code:GetWallpaperEngineProjects}\SignalRGB_Glow_Screen3"

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
