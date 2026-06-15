# SignalRGB → Desktop Wallpaper — Handoff Notes

Stand: 2026-05-17. **Active architecture: Multi-screen (1..3) HTML Lively
wallpapers + Python bridge that routes UDP-frames to screen-tagged WS
subscribers.** Tray-Icon-Settings (Phase 2) und Inno-Setup-Installer
(Phase 3) sind work-in-progress — Phase 1 (Multi-Screen-Plumbing) ist
fertig und smoke-getestet.

## Goal

Make SignalRGB effects visible as an RGB glow on the desktop wallpaper.
Target: Lively. Not a 1:1 pixel mirror of the canvas — instead, a prepared
image with transparent cut-outs (windows, signs, etc.) sits on top of a
coloured glow layer, so the cut-outs light up in the current effect colours.

## Architecture (Phase 1 — Multi-Screen-Plumbing)

```text
SignalRGB Plugin (network-type)
   │  Plugin-Setting screenCount (1/2/3) -> announces N controllers
   │  ("Desktop Wallpaper - Screen 1/2/3"), each ist eigenes Device.
   │
   │  UDP 127.0.0.1:17320
   │  Wire: [magic "SR"][screen u8][w u16 BE][h u16 BE][rgb...]
   ▼
SignalRGBBridge.exe  (PyInstaller --onefile --noconsole)
   ├─ UDP listener :17320  parsed screen-Byte, routet per Screen-Index
   ├─ WebSocket server :17320/?screen=N  Pro-Screen-Fan-Out
   └─ HTTP image proxy :17320 /image?path=…  (CEF file:// Sandbox workaround)
   │
   │  ws:// nur an Clients mit passendem ?screen=N
   ▼
Lively HTML wallpaper (HTML/JS in CEF) — pro Monitor eine Zip
   ├─ <meta name="signalrgb-screen-index" content="0|1|2"> (per Zip patched)
   ├─ connectet zu ws://127.0.0.1:17320/?screen=<meta-value>
   └─ rendered Frames in CSS-Grid mit Image-Overlay
```

## Files

| Pfad | Was |
| --- | --- |
| `SignalRGB_Desktop_Wallpaper.js` | SignalRGB-Plugin v0.2 (multi-screen). Aktive Quelle: `OneDrive\Dokumente\WhirlwindFX\Plugins\`. |
| `SignalRGB_Desktop_Wallpaper.qml` | UI/Service-Page für das Plugin. |
| `wallpaper_bridge/bridge.py` | UDP→WS+HTTP-Bridge (multi-screen routing), stdlib only. |
| `wallpaper_bridge/smoke_test.py` | Dev-Test: sendet fake UDP, verifiziert Routing per ?screen=N. |
| `wallpaper_bridge/dist_bridge/SignalRGBBridge.exe` | Aktueller PyInstaller-Build (Phase 1). |
| `wallpaper_bridge/wallpaper/` | Template-Bundle: `LivelyInfo.json` mit `__SCREEN_LABEL__` placeholder, `index.html` mit `content="0"` default, `LivelyProperties.json`, `images/`. |
| `wallpaper_bridge/SignalRGB_Glow_Screen1.zip` | Lively-Zip pro Monitor 1 (meta=0). |
| `wallpaper_bridge/SignalRGB_Glow_Screen2.zip` | Pro Monitor 2 (meta=1). |
| `wallpaper_bridge/SignalRGB_Glow_Screen3.zip` | Pro Monitor 3 (meta=2). |

## Bundle-Build

Build-Skript ist inline in der PowerShell-History (siehe Phase-1-Turn vom
2026-05-17). Im Kern: copy `wallpaper/` -> stage_screenN -> `index.html`'s
`content="0"` patchen auf `content="N"`, `LivelyInfo.json`'s
`__SCREEN_LABEL__` mit `(N+1)` ersetzen, dann zippen.

## Phase 1 Quick-Test-Flow (vor Installer/Tray)

1. Plugin liegt schon in `OneDrive\Dokumente\WhirlwindFX\Plugins\` —
   SignalRGB hot-loaded automatisch beim File-Write.
2. Bridge starten:
   `wallpaper_bridge\dist_bridge\SignalRGBBridge.exe` (doppelklick).
   Kein Console-Fenster (`--noconsole`), läuft im Hintergrund. Killen via
   Task-Manager.
3. In SignalRGB: Device "Desktop Wallpaper - Screen 1" sollte auftauchen.
   Für Multi-Screen: Plugin-Settings → "Number of Screens" auf 2 oder 3.
   SignalRGB zeigt dann "Screen 2", "Screen 3" zusätzlich. Auf Canvas
   platzieren wie gewünscht.
4. Lively-Zips drag-and-drop importieren:
   - `SignalRGB_Glow_Screen1.zip` → Monitor 1
   - `SignalRGB_Glow_Screen2.zip` → Monitor 2 (falls vorhanden)
   - `SignalRGB_Glow_Screen3.zip` → Monitor 3 (falls vorhanden)
5. Wallpaper aktivieren. Status-Overlay (oben links, kurz) zeigt
   `screen N live WxH @ fps`.

## End-User-Flow (geplant, nach Phase 3)

Inno-Setup-Installer kopiert Plugin in Plugins-Ordner, installiert
Bridge+Tray nach `C:\Program Files\SignalRGBWallpaper\` (v2.2.1+;
pre-2.2.1 lag's unter `%LOCALAPPDATA%\Programs\SignalRGBWallpaper\`),
registriert
HKCU\Run für Autostart, öffnet am Ende Lively-Import-Dialog für die 3
Zips. User-Interaktion: 1× Installer, 1× pro Monitor in Lively den
passenden Zip aktivieren.

## SignalRGB-Plugin

- Properties: `gridSize` (combobox 8/16/32, default 32), `targetFps` (15/30/60, default 30),
  `bridgePort` (default 17320), `LightingMode` (Canvas/Forced), `forcedColor`,
  `shutdownColor`.
- Sendet jedes Frame als ein UDP-Paket nach 127.0.0.1:`bridgePort`.
- `DiscoveryService` registriert einen virtuellen Controller bei Plugin-Load
  und ruft `service.announceController(this)` in `update()` — DAS ist der
  Schlüssel, ohne den SignalRGB den Controller nicht zum Device promotet.

## SignalRGBBridge.exe rebuilden

```powershell
cd wallpaper_bridge
python -m pip install --user pyinstaller   # falls nötig
python -m PyInstaller --onefile --noconsole --name SignalRGBBridge bridge.py
copy dist\SignalRGBBridge.exe wallpaper\SignalRGBBridge.exe
# danach das Lively-Zip neu packen:
Compress-Archive -Path wallpaper\* -DestinationPath SignalRGB_Glow_Lively.zip -Force
```

## Wichtige Gotchas die wir gelernt haben

- **SignalRGB-Plugin-Sandbox** hat `@SignalRGB/udp` (server+client), HID,
  `XMLHttpRequest`. KEIN `@SignalRGB/tcp` (nur in Doku, real nicht da —
  am 2026-05-17 nochmal mit Probe-Plugin verifiziert, Fehler beim Modul-Load:
  *"Could not open module file:///.../@SignalRGB/tcp for reading"*),
  KEIN `WebSocket`, KEIN Datei-IO. Daher braucht es zwingend einen externen
  UDP→WS-Bridge-Prozess.
- **`device.setFrameRateTarget(N)`** existiert aber ist undokumentiert.
  Engine-Cap ist 60 fps. Werte ≥120 werden auf 60 gecapped.
- **`service.announceController(this)`** ist der Magic Call, der einen
  Controller zum Device promotet. Govee macht das in `update()` mit
  `if (!this.initialized)`-Guard.
- **Lively `LivelyInfo.json` Types:** 0 = Application, 1 = Web. Wir nutzen 1.
  Lively startet KEINE Helper-Prozesse für Web-Wallpaper — daher die
  HKCU-Run-Lösung im Setup.bat.
- **Lively Web-Wallpaper / CEF** blockieren `file://` außerhalb des
  Projektordners. Der HTTP-Image-Proxy in der Bridge ist der Workaround.
- **Lively Store-Version** (MSIX) und auch die GitHub-Version können beide
  problemlos das Web-Wallpaper laden. Lively startet die Helper-Exe NICHT
  selbst — das übernimmt der HKCU-Run-Eintrag.
- **HKCU Run vs. Scheduled Task:** HKCU Run gewählt, weil kein UAC nötig.
  `schtasks /rl highest` würde Admin verlangen, `/rl limited` ist möglich
  aber unnötig komplex. Run-Key reicht für einen Localhost-Listener.

## Was verworfen wurde (Git-History für Details)

- **WE Application Wallpaper + Go/Python WebView2**: WE reparented unser
  Window per `SetParent` mid-`CreateCoreWebView2Controller`. Race-Condition,
  HRESULT 0x80070578, WebView2 stirbt. Pywebview-Variante fängt's ab aber
  rendert nicht. Verworfen.
- **Lively MSIX (Store) + Application Wallpaper (Type 0)**: MSIX-Sandbox
  blockt `.exe`-Wallpaper hardcoded. Verworfen.
- **Lively non-MSIX + Go+WebView2 (Type 0)** — `wallpaper_go/`, 2026-05-17.
  **Funktioniert technisch**: Race-Condition lässt sich umgehen, weil Lively
  vor `SetParent` auf `WaitForInputIdle` + sichtbares Top-Level-Window wartet
  (`ProcessExtensions.WaitForProcessOrGameWindow`). jchv's `Embed()` blockt
  derweil in einem Message-Pump bis WebView2 fertig ist → bis Lively reparented
  ist die WebView lebendig. Single-Process Setup (UDP + WS + HTTP + WebView2),
  keine Bridge nötig.
  **Aber verworfen wegen Settings**: Lively liefert für Type-0-Wallpaper
  grundsätzlich KEINE Properties an die EXE.
  Beleg im Lively-Source:
  - `ExtPrograms.cs`: `LivelyPropertyCopyPath => null`, `SendMessage(...) //todo`
  - `WallpaperPluginFactory.cs:156`: für `WallpaperType.app` wird
    `CreateLivelyPropertyFolder` gar nicht erst aufgerufen
  - `Systray.cs:246` + `WallpaperLayoutViewModel.cs:177`: Customise-Button
    explizit nur enabled wenn `LivelyPropertyCopyPath != null`
  - Lively-Wiki: *"If the application requires commandline arguments,
    currently there is no gui way to enter this at the moment."*
  Damit kein Hintergrund-Picker, kein Layout-Switcher, keine Slider über
  Lively's UI. Eigene Settings-UI (Tray-Icon o.ä.) wäre Aufwand → zurück
  zu Type 1 + Bridge.
- **Plugin selbst macht WebSocket-Server**: `@SignalRGB/tcp` existiert nicht
  in der Runtime trotz Doku. UDP-Server im Plugin würde gehen, hilft aber
  nichts weil Browser kein UDP empfangen kann.

## SignalRGB-Plugin verbleibt im aktiven Sync

Die `OneDrive\Dokumente\WhirlwindFX\Plugins\SignalRGB_Desktop_Wallpaper.{js,qml}`
sind weiterhin von SignalRGB geladen. Solange das Plugin aktiv ist sendet
es UDP-Pakete an 127.0.0.1:17320 — wenn nichts auf dem Port lauscht ist das
harmlos (UDP wird gedroppt, ICMP unreachable). Will man's los: Plugin in
SignalRGB deaktivieren oder die `.js`/`.qml` aus dem Plugins-Folder löschen.
