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
Name: "autostart"; Description: "Start bridge automatically on logon"; \
  GroupDescription: "Additional setup:"; Flags: checkedonce
Name: "installplugin"; Description: "Install the SignalRGB Desktop Wallpaper plugin into the WhirlwindFX Plugins folder"; \
  GroupDescription: "Additional setup:"; Flags: checkedonce

[Files]
; Bridge + tray
Source: "..\wallpaper_bridge\dist_bridge\SignalRGBBridge.exe"; DestDir: "{app}"; Flags: ignoreversion

; SignalRGB plugin (only if user opted in)
Source: "..\SignalRGB_Desktop_Wallpaper.js";  DestDir: "{userdocs}\WhirlwindFX\Plugins"; \
  Flags: ignoreversion; Tasks: installplugin
Source: "..\SignalRGB_Desktop_Wallpaper.qml"; DestDir: "{userdocs}\WhirlwindFX\Plugins"; \
  Flags: ignoreversion; Tasks: installplugin

; Lively wallpaper zips (user drags into Lively after install)
Source: "..\wallpaper_bridge\SignalRGB_Glow_Screen1.zip"; DestDir: "{app}\Lively wallpapers"; Flags: ignoreversion
Source: "..\wallpaper_bridge\SignalRGB_Glow_Screen2.zip"; DestDir: "{app}\Lively wallpapers"; Flags: ignoreversion
Source: "..\wallpaper_bridge\SignalRGB_Glow_Screen3.zip"; DestDir: "{app}\Lively wallpapers"; Flags: ignoreversion

; Docs (so the user has a local copy)
Source: "..\LICENSE";      DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md";    DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SignalRGB Wallpaper Bridge"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Lively wallpapers folder";   Filename: "{app}\Lively wallpapers"
Name: "{group}\Documentation (README)";     Filename: "{app}\README.md"
Name: "{group}\Uninstall SignalRGB Wallpaper"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "SignalRGBWallpaperBridge"; \
  ValueData: """{app}\{#MyAppExeName}"""; \
  Flags: uninsdeletevalue; Tasks: autostart

[Run]
; Open the Lively-wallpapers folder so the user can drag the zips into Lively
Filename: "{app}\Lively wallpapers"; Verb: open; \
  Description: "Open the Lively wallpapers folder (drag the zips onto Lively)"; \
  Flags: postinstall skipifsilent shellexec nowait
; Start the bridge right away (only if user kept autostart)
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Start the SignalRGB Wallpaper Bridge now"; \
  Flags: postinstall skipifsilent nowait; Tasks: autostart

[UninstallRun]
; Make sure the running bridge releases its file handles before uninstall
; tries to delete the exe.
Filename: "{cmd}"; Parameters: "/c taskkill /f /im SignalRGBBridge.exe"; \
  Flags: runhidden; RunOnceId: "KillBridge"
