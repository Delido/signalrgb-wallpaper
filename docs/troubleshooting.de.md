# Fehlerbehebung

Häufige Fehler und wie man sie diagnostiziert.

## Wie man brauchbare Diagnose-Ausgabe bekommt

Der Default-`SignalRGBBridge.exe`-Build ist `--noconsole` — kein
stdout sichtbar. Wenn sich was komisch verhält, die Bridge stattdessen
mit sichtbarem stdout starten:

**Option A** — die Python-Quelle direkt ausführen:

```powershell
python wallpaper_bridge\bridge.py
```

Du siehst UDP-Paketzählungen, WS-Client-Connects, Settings-Pushes
etc. Plus jede Python-Exception.

**Option B** — die `.exe` aus cmd starten damit stdout/stderr ans
Terminal vererben (funktioniert nur teilweise da `--noconsole` das
Handle strippt — für Debugging bitte Option A bevorzugen).

Für SignalRGB-seitige Plugin-Probleme schreibt das Plugin seine
`service.log` / `device.log`-Aufrufe in SignalRGBs Plugin-Log:
`%LOCALAPPDATA%\WhirlwindFX\SignalRgb\Logs\SignalRGB_*.log`

## Plugin erscheint nicht

Nach Kopieren von `SignalRGB_Desktop_Wallpaper.js` und `.qml` in den
Plugins-Ordner sollte SignalRGB innerhalb von Sekunden Hot-Loading
durchführen.

Wenn das Gerät nicht auftaucht:

1. **Plugins-Ordner-Pfad prüfen.** Mit OneDrive-Documents-Redirection
   ist es `%USERPROFILE%\OneDrive\Documents\WhirlwindFX\Plugins\`
   (oder `OneDrive\Dokumente\…` auf deutschem Windows). Ohne
   Redirection `%USERPROFILE%\Documents\WhirlwindFX\Plugins\`.
   SignalRGB beobachtet nur den umgeleiteten Pfad.
2. **SignalRGB neu starten.** Rechtsklick aufs SignalRGB-Tray-Icon →
   Quit, dann neu starten. Hot-Reload triggert
   `DiscoveryService.Initialize` manchmal nicht zuverlässig; ein
   vollständiger Neustart tut's immer.
3. **SignalRGB-Log prüfen** (`SignalRGB_*.log`, siehe oben) — nach
   `Custom Plugin File Loaded` suchen um zu bestätigen dass SignalRGB
   deine Datei gesehen hat. Wenn `Error: Could not open module…`
   auftaucht, ist das ein Plugin-Laufzeitfehler — bitte Issue
   einreichen mit dem genauen Fehler.

## Bridge startet nicht

Symptom: du doppelklickst `SignalRGBBridge.exe`, kein Tray-Icon, gar
nichts.

1. **Task-Manager → Details** öffnen und nach
   `SignalRGBBridge.exe` suchen. Wenn nicht da, ist der EXE-Start
   fehlgeschlagen (wahrscheinlich Antivirus-Quarantäne auf dem
   PyInstaller-Bundle — AV vorübergehend deaktivieren / Ausschluss
   hinzufügen und nochmal versuchen, oder aus Quellcode bauen).
2. **Port 17320 schon belegt** — eine andere Bridge läuft bereits
   (oder ein anderes Programm nutzt 17320). Prüfen:

   ```powershell
   Get-NetUDPEndpoint -LocalPort 17320 -ErrorAction SilentlyContinue
   Get-NetTCPConnection -LocalPort 17320 -State Listen -ErrorAction SilentlyContinue
   ```

   Wenn etwas anderes gebunden ist, killen (oder `bridgePort` in den
   Plugin-Einstellungen ändern — dann müsstest du aber auch die Zips
   mit dem passenden Port neu bauen… nicht schön, lieber den
   konfligierenden Prozess killen).

## Wallpaper bleibt schwarz / "connecting…"-Status

Das Lively-Wallpaper öffnet sich aber bekommt nie Frames.

1. **Debug-Overlay** für diesen Bildschirm aktivieren: Tray-Icon →
   **Configurator…** → den Bildschirm-Tab wählen → *Hintergrund* →
   *Debug-Overlay anzeigen (Status-Zeile oben links)* aktivieren. Das
   Wallpaper zeigt jetzt eine kleine Status-Zeile oben links.
2. **Status lesen:**
   - `connecting ws://127.0.0.1:17320/?screen=N…` — Bridge läuft
     nicht oder falscher Port. Prüfen ob `SignalRGBBridge.exe` im
     Tray ist.
   - `disconnected — retrying…` — Bridge ist abgestürzt oder wurde
     gekillt. Neu starten.
   - `screen N live WxH @ X fps` — Wallpaper ist verbunden und
     bekommt Frames. Wenn du trotzdem kein Glow siehst, liegt's auf
     der SignalRGB-Seite: prüfen ob das Gerät auf der Leinwand ist
     und ein farbiger Effekt aktiv ist.
3. **Plugin sendet UDP?** In SignalRGBs Log (`SignalRGB_*.log`) nach
   `[DesktopWallpaper] screen N frame #` suchen. Wenn da, feuert das
   Plugin; wenn nicht, wird das Gerät nicht von SignalRGB gerendert
   (nicht auf der Leinwand / nicht aktiv).

## Falsche Farben auf falschem Monitor

Du hast zwei Monitore eingerichtet, aber die Farben von Screen 1
erscheinen auf Monitor 2 (oder ähnlich).

Das Mapping passiert in **Lively**, nicht in unserem Code. Jeder
Wallpaper-Zip hat einen Screen-Index im HTML-`<meta>`-Tag
hartcodiert:

| Zip | Abonniert |
| --- | --- |
| `SignalRGB_Glow_Screen1.zip` | UDP-Frames mit `screen=0` |
| `SignalRGB_Glow_Screen2.zip` | UDP-Frames mit `screen=1` |
| `SignalRGB_Glow_Screen3.zip` | UDP-Frames mit `screen=2` |

Und die SignalRGB-Geräte passen dazu:

- "Desktop Wallpaper - Screen 1" sendet UDP mit `screen=0`-Byte
- "Desktop Wallpaper - Screen 2" sendet mit `screen=1`
- "Desktop Wallpaper - Screen 3" sendet mit `screen=2`

Die Kette ist also: SignalRGB-Gerät "Screen 1" → UDP screen=0 →
Bridge routet zu WS-Clients mit `?screen=0` → Wallpaper aus
`Screen1.zip`.

Um das Mapping zu fixen, einfach tauschen auf welchem Monitor jedes
Lively-Wallpaper aktiviert ist. Oder die SignalRGB-Canvas-
Platzierungen umsortieren.

## Debug-Overlay erscheint trotz Deaktivierung

Sollte in v0.2.0 gefixt sein. Wenn es nach Update trotzdem auftaucht,
einen Hard-Refresh machen:

- In Lively das Wallpaper deaktivieren, dann reaktivieren. Das lädt
  die HTML-Seite mit aktuellem Code neu.
- Wenn es trotzdem leakt, bitte Issue einreichen.

## Tray-Quit killt die Bridge nicht

Sollte in v0.2.0 gefixt sein. Wenn Quit-Klick `SignalRGBBridge.exe`
im Task-Manager stehen lässt, manuell aus Task-Manager → Task beenden
killen. Dann Issue mit deinem Windows-Build (`winver`) einreichen.

## Hintergrundbild lädt nicht

Symptom: das Wallpaper rendert das Glow korrekt aber kein
Hintergrundbild erscheint (oder es ist kaputt).

1. **Pfad-Problem** — prüfen ob die Datei am gewählten Pfad noch
   existiert. Im Datei-Explorer hingehen.
2. **Unsupported Extension** — der Image-Proxy der Bridge erlaubt
   `.png .jpg .jpeg .gif .webp .svg .bmp .ico`. Andere Formate werden
   abgelehnt.
3. **Bridge offline** — ohne die Bridge kann das Wallpaper keine
   absoluten Pfade via `/image`-Proxy laden.
4. Dev-Tools des Wallpapers öffnen (Lively in Debug-Mode) und
   Netzwerk-Requests inspizieren. Oder stdout der Bridge (aus
   Python-Quelle gestartet) nach `[http] served …` und
   `404 not found` durchsuchen.

## SignalRGB zeigt zu viele / zu wenige Geräte

*Anzahl Bildschirme* im Configurator setzen (rechts oben in der
Tab-Leiste — *Bildschirme: 1 / 2 / 3 / 4*). Das Plugin pollt die
Bridge alle ~2 Sekunden und passt an. Wenn nicht:

- Sicherstellen dass die Bridge tatsächlich läuft (Tray-Icon
  sichtbar).
- `http://127.0.0.1:17320/config` im Browser öffnen — sollte
  `{"screenCount": N}` liefern. Wenn die Seite fehlschlägt, läuft
  die Bridge nicht oder der Endpoint ist kaputt.
- SignalRGB neu starten wenn das Plugin festhängt.

## Livelys "Wallpaper pausieren" stoppt das Glow nicht

Die Wallpaper-Seite implementiert Livelys
`window.livelyWallpaperPlaybackChanged(state)`-Hook gemäß
[Wiki-Spec](https://github.com/rocksdanister/lively/wiki/Web-Guide-V-:-System-Data)
und zeigt ein rotes "⏸ PAUSED"-Badge oben rechts wenn der Hook
feuert. Außerdem subscribt sie `document.visibilitychange` als
defensiven Fallback für Hosts die die Surface suspenden ohne den
Lively-Event zu feuern. Wir geben absichtlich **nicht**
`--pause-event true` in `LivelyInfo.Arguments` mit — neuere
Lively-Builds lehnen das als unbekannte Option ab
(Wallpaper-Plugin-Exception beim Import). Der Pause-Hook feuert auf
Builds die ihn ohne Opt-in pushen weiterhin.

**Aber** ob einer der Hooks tatsächlich feuert hängt vom
Lively-Build und der Umgebung ab — manche Setups liefern den
Suspend-IPC gar nicht an den WebView2-Player, in dem Fall ist der
visibilitychange-Fallback das einzige Signal das die Seite kriegt.

Schnellcheck: wenn du in Livelys Tray "Wallpaper pausieren" klickst,
pausieren **andere** Web-Typ-Wallpaper in deiner Library tatsächlich
(frieren ein)?

- **Nein** → Lively selbst pausiert in deiner Umgebung nicht. Das
  ist ein Lively-seitiges Problem; wir können das nicht von einer
  Wallpaper-Seite aus umgehen. Issue beim
  [Lively-Repo](https://github.com/rocksdanister/lively/issues)
  einreichen mit deiner Lively-Version und Windows-Build.
- **Ja bei anderen aber nicht bei unserem** → Issue gegen dieses
  Projekt einreichen mit deiner Lively-Version
  (`Einstellungen → Über` in Lively).

## Wallpaper aktualisiert aber Lively zeigt noch die alte Version

Symptom: du hast einen Wallpaper-Zip neu gebaut + reimportiert (oder
einen neuen Release gezogen), aber das Wallpaper in Lively rendert
weiter das alte Verhalten — altes Layout, kein Parallax, fehlende
Widgets.

Lively entpackt jeden importierten Wallpaper-Zip **einmal** in einen
Random-Hash-Ordner unter
`%USERPROFILE%\AppData\Local\Lively Wallpaper\Library\wallpapers\<hash>\`
(MSIX-Build hat anderen Pfad; beide enden in
`Library\wallpapers\<hash>\`). Den Quell-Ordner neu zu zippen
**propagiert nicht** — Lively liest den Original-Zip nie neu.

Um neue HTML / JS / `LivelyInfo.json`-Änderungen zu übernehmen:

1. In Livelys **Library** Rechtsklick aufs Wallpaper → **Löschen**.
2. Den neuen Zip auf Lively ziehen (oder den Installer mit
   *Auto-Import in Lively* erneut laufen lassen — v0.7.0+ benutzt
   deterministische Ordnernamen `signalrgb-glow-screen-{1,2,3}\`,
   die der Installer in-place überschreibt, also kein manuelles
   Löschen für zukünftige Updates).
3. Jede neue Kachel rechtsklicken → **Als Wallpaper setzen** für
   den passenden Monitor.

Der deterministische Auto-Import ist der v0.7.0-Fix speziell für
diesen Footgun. Pre-v0.7.0-User die von manuellem Drag-Import
kommen, treffen es einmal beim Upgrade — nach Installer-Übernahme
sind nachfolgende Updates lautlos.

## Lively-Import schlägt fehl: "Unknown options are passed. WallpaperPluginException"

Wenn Lively *Error initializing — Unknown options are passed.
Exception: WallpaperPluginException* beim Import zeigt, bist du auf
den kaputten **v0.7.0** Lively-Bundles —
`LivelyInfo.Arguments` trug einen ungültigen `--system-cursor true`
Wert den Lively beim Import ablehnt. Gefixt in **v0.7.1**
(Arguments auf `null` zurückgesetzt).

Zur Wiederherstellung:

1. **v0.7.1** oder neuer installieren (Installer mit
   *Auto-Import in Lively* nochmal laufen lassen, oder die frischen
   `SignalRGB_Glow_ScreenN.zip` von der Release-Seite holen).
2. In Livelys Library die kaputten Kacheln löschen (der Import-Error
   hinterlässt einen Stub-Eintrag), dann den frischen Zip
   reimportieren.

Die Parallax + cursor-gesteuerten Pixelfx-Effekte funktionieren auf
v0.7.1 weiter — sie kriegen den Cursor durchs DOM-`mousemove`-Event
sobald Livelys *Wallpaper interaction* Setting an ist, statt durch
das abgelehnte Argument.

## Parallax / Cursor-Effekte reagieren in Lively nicht

Das 3D-Parallax (Configurator → Effekte → *3D-Parallax*) und die
maus-gesteuerten Pixelfx-Modi (*Trail*, *Glow*, *Ripple — alle*)
brauchen Echtzeit-Cursor-Koordinaten. v0.7.1 liest sie aus den
DOM-`mousemove`-Events der Wallpaper-Seite, die nur feuern wenn die
Wallpaper-Surface von echten Maus-Events erreichbar ist:

- **Lively** — die *Wallpaper interaction*-Einstellung des Wallpapers
  auf **on** stellen (Rechtsklick auf aktive Kachel → *Customise* →
  oben im Panel). Click-Through-Modus liefert keine DOM-mousemove-
  Events an die Seite, also bleibt das Parallax / Pixelfx still.
- **Wallpaper Engine** — *Mouse input* auf *Allow* setzen. Gleiche
  Logik.
- **Builder / Configurator-Vorschau / Browser-Tab** — funktioniert
  automatisch; das sind normale interaktive Web-Seiten.

Click-getriebene Pixelfx (der *Ripple*-Modus) braucht zusätzlich
echte Klicks am Wallpaper, das ist die gleiche Anforderung wie
*interaction-on*.

## SignalRGB-Plugin Glow Grid Base Size > 36 wirft Fehler

Symptom: in den Plugin-Einstellungen von SignalRGB drehst du
*Glow Grid Base Size* auf **64**, **96** oder **128**, klickst Save,
und SignalRGBs Log zeigt:

```text
udp.error - Buffer too large. Max size is 4096 bytes!
```

Das ist das harte 4 KB `udp.send()`-Limit der SignalRGB-Plugin-
Sandbox. Plugin und Bridge **unterstützen** zwar größere Grids —
v0.6.0+ chunked Frames > 4 KB über mehrere Datagramme (`SC`-Wire-
Format) und die Bridge fügt sie zusammen.

Wenn du den Fehler siehst:

- **Bundle-Versionen prüfen ob sie matchen.** Sowohl
  `SignalRGBBridge.exe` als auch `SignalRGB_Desktop_Wallpaper.js`
  müssen ≥ v0.6.0 sein — das gechunkte Protokoll ist in beiden
  Hälften implementiert. Alte Plugin-Datei + neue Bridge (oder
  umgekehrt) fallen zurück auf das Single-Packet-`SR`-Format und
  treffen das Limit.
- **Installer nochmal laufen lassen** mit *SignalRGB-Desktop-
  Wallpaper-Plugin installieren* aktiv um die passenden JS / QML
  in `Documents\WhirlwindFX\Plugins\` zu legen.
- Dann wieder **64 / 96 / 128** in den Plugin-Einstellungen wählen.

## Plugin Aspect Ratio = Auto, aber Glow-Grid bleibt quadratisch

Der *Auto*-Modus des Plugins liest den Viewport pro Bildschirm aus
dem `GET /config`-Endpoint der Bridge, und die Bridge kennt den
Viewport erst sobald eine Wallpaper-Seite per WebSocket verbunden ist
und ihr `{type:"viewport", w, h}` Frame gepusht hat. Davor fällt
*Auto* auf 16:9 zurück.

Schritte zum Prüfen:

1. **Läuft das Wallpaper tatsächlich?** Wallpaper in Lively /
   Wallpaper Engine für diesen Screen-Index setzen. Der Viewport
   wird bei WS-Open + bei `window.resize` (debounced) gesendet.
2. **Sieht die Bridge ihn?** `http://127.0.0.1:17320/config` im
   Browser öffnen — das `screens[]`-Array sollte
   `{viewportW: …, viewportH: …}` für jeden verbundenen Screen
   gefüllt zeigen.
3. **Liest das Plugin ihn?** SignalRGB-Log (`SignalRGB_*.log`)
   prüfen; bei jedem Update-Tick XHRt das Plugin `/config` und
   aktualisiert seinen internen Viewport-Cache. Ein Grid-Change
   wird als `screen N grid CxR (aspect=Auto)` geloggt — prüfen ob
   die Zahlen zum Monitor passen.

Wenn das Wallpaper läuft aber der Viewport immer noch 0 ist, war der
WS-Connect vor dieser Beta. Wallpaper neu laden (Lively: Rechtsklick
→ *Aussetzen* + *Als Wallpaper setzen*; WE: ähnlich) um den
`viewport`-Push zu re-triggern.

Wenn du nicht auf Auto vertrauen willst, eine feste Aspect Ratio
wählen (*16:9* / *21:9* / *32:9* / *9:16*) oder *Custom* + Cols ×
Rows eintippen.

## Windows Defender flaggt `SignalRGBBridge.exe` als Trojan:Win32/Wacatac.C!ml

Das ist ein False Positive auf dem PyInstaller-`--onedir`-Build.
`Wacatac.C!ml` ist eine ML-Heuristik-Erkennung — sie feuert bei
vielen PyInstaller-gepackten Python-Anwendungen weil das Bootloader-
Muster (kleine native EXE die Python-Interpreter + Bytecode in
`_internal/` beim Start auspackt) sich mit verbreiteten Malware-
Packern überschneidet.

**Die Bridge macht nichts Bösartiges.** Quellcode auf
[github.com/Delido/signalrgb-wallpaper](https://github.com/Delido/signalrgb-wallpaper)
und der Build ist reproduzierbar (`pwsh installer\build.ps1`).

### Wiederherstellung

1. *Windows-Sicherheit → Viren- & Bedrohungsschutz →
   Schutzverlauf* öffnen → den Wacatac-Eintrag anklicken →
   **Aktionen → Zulassen**.
2. Falls die Datei in Quarantäne war: **Aktionen → Wiederherstellen**.
   Falls Wiederherstellen ausgegraut ist, Installer nochmal laufen
   lassen — er legt eine frische Kopie am Original-Pfad ab.
3. (Optional, nur wenn es weiter re-flagged) *Windows-Sicherheit →
   Viren- & Bedrohungsschutz → Einstellungen verwalten →
   Ausschlüsse → Ausschluss hinzufügen → Ordner*, und
   `C:\Program Files\SignalRGBWallpaper` wählen (v2.2.1+
   Install-Pfad; ältere Versionen lagen unter
   `%LOCALAPPDATA%\Programs\SignalRGBWallpaper`).

### False Positives für alle reduzieren helfen

Das Microsoft-Defender-Team nimmt False-Positive-Reports an unter
[microsoft.com/wdsi/filesubmission](https://www.microsoft.com/en-us/wdsi/filesubmission).
Eine Submission mit dem Installer oder `SignalRGBBridge.exe` cleart
den spezifischen Build-Hash typisch innerhalb von 24-72 Stunden und
trainiert das ML-Modell weg von dieser Signatur für künftige Builds.
Kostenlos, dauert ~2 min, braucht ein kostenloses Microsoft-Konto.

## "Address already in use" beim Bridge-Start

Port 17320 ist von einem alten Bridge-Prozess belegt der nicht
sauber beendet wurde. Entweder:

```powershell
Get-Process -Name SignalRGBBridge -ErrorAction SilentlyContinue | Stop-Process -Force
```

Oder Task-Manager → alle `SignalRGBBridge.exe`-Einträge beenden.
Dann neu starten.

## Steckst du immer noch fest?

Issue einreichen bei
[github.com/Delido/signalrgb-wallpaper/issues](https://github.com/Delido/signalrgb-wallpaper/issues)
mit:

- Windows-Version (`winver`)
- SignalRGB-Version
- Lively-Version (und ob Store- oder GitHub-Build)
- Was du gemacht hast, was du erwartet hast, was passiert ist
- Bridge-stdout-Ausgabe (`python wallpaper_bridge\bridge.py` ausführen)
- SignalRGB-Log-Auszug wenn relevant (Zeilen mit `DesktopWallpaper`)
