# Installation

Die Langfassung des [README-Schnellstarts](https://github.com/Delido/signalrgb-wallpaper/blob/main/README.md#quick-start),
mit exakten Pfaden und den Windows-Details, an denen die meisten hängen
bleiben.

## Voraussetzungen

Vor dem Start prüfen dass das hier funktioniert:

1. **SignalRGB** — [signalrgb.com](https://www.signalrgb.com/). Einmal
   öffnen und einen beliebigen Effekt wählen; wenn keine LEDs leuchten,
   erst das fixen. Dieses Projekt setzt auf SignalRGBs Effekt-Canvas
   auf, SignalRGB muss daher funktionsfähig sein.
2. **Ein Wallpaper-Host** — mindestens einen wählen (der Installer
   fragt):
   - **Lively Wallpaper** (kostenlos, empfohlen) —
     [rocksdanister.com/lively](https://www.rocksdanister.com/lively/).
     Der GitHub-Installer-Build wird bevorzugt; der Microsoft-Store-
     bzw. MSIX-Build funktioniert auch.
   - **Wallpaper Engine** (kostenpflichtig, auf Steam) — wird vom
     Installer automatisch erkannt; Bundles werden direkt in Steams
     `wallpaper_engine\projects\myprojects`-Ordner kopiert.
3. **Windows 10 oder 11**. Keine weiteren Abhängigkeiten — die Bridge
   liefert als eine einzelne, eigenständige `.exe` (Python + Tk +
   Pillow + psutil + pystray alle von PyInstaller mitgepackt).

## Einfacher Weg: Installer

Lade die aktuelle `SignalRGBWallpaperSetup-<version>.exe` von der
[Releases-Seite](https://github.com/Delido/signalrgb-wallpaper/releases/latest)
und führe sie aus. Den UAC-Prompt bestätigen — der Installer legt die
Bridge unter `C:\Program Files\SignalRGBWallpaper\` ab, damit Windows
Defender nicht mehr unsignierte Binaries in beschreibbaren
`%LOCALAPPDATA%`-Pfaden anflaggt. Deine Library + Einstellungen pro
Bildschirm bleiben unter `%LOCALAPPDATA%\SignalRGBWallpaper\`
(Nutzerdaten, kein Code).

### Installer-Durchlauf

Der Wizard hat sechs Schritte. Der Reihe nach durchklicken — die
Voreinstellungen passen für Neuinstallationen, und beim Update werden
die gleichen Voreinstellungen erneut verwendet, du kannst also meistens
einfach Enter halten.

#### 1. Sprache

![Sprachauswahl](images/installer/01-language.png)

Der Wizard bietet Deutsch und Englisch. Nach Belieben wählen — der
Rest des Wizards, das Tray-Menü, der "Über"-Dialog und der
Configurator folgen nach dem Install der gleichen Einstellung (die
Bridge erkennt beim Start zusätzlich deine Windows-Locale, sofern du
nicht explizit `"language"` in `config.json` setzt).

#### 2. Lizenz

![Lizenzvereinbarung](images/installer/02-license.png)

MIT-Lizenz, das ganze Projekt ist Open Source. Akzeptieren und auf
*Weiter* klicken.

#### 3. Aufgaben (die Seite die die eigentliche Arbeit macht)

![Tasks-Seite — Auto-Lively + WE + Autostart](images/installer/03-tasks.png)

Das ist die wichtigste Seite. Die Voreinstellungen entsprechen dem
häufigsten Szenario (Lively + Auto-Import + Lively automatisch
installieren wenn fehlend + WE Auto-Copy wenn Steam erkannt wurde):

**Wallpaper-Host:**

- ☑ **Lively Wallpaper** (standardmäßig an) — nötig für den
  Lively-Pfad.
- ☑ **Automatisch in Livelys Library importieren** (Unter-Task) —
  wenn dieser Task und eine Lively-Installation (GitHub oder MSIX)
  beide vorhanden sind, werden die vier Glow-Bundles direkt nach
  `Library\wallpapers\signalrgb-glow-screen-{1,2,3,4}\` mit
  deterministischen Ordnernamen entpackt. Jeder weitere
  Installer-Lauf überschreibt in-place — kein *"löschen und nach
  jedem Update neu importieren"* mehr.
- ☐ **Lively Wallpaper automatisch installieren wenn nicht
  vorhanden** — *Opt-in.* Wenn aktiv UND Lively nicht auf der
  Festplatte ist, lädt der Installer das neueste Release von GitHub
  und installiert es still *vor* dem Auto-Import. Standardmäßig aus,
  weil es Netzwerk-Traffic beim Install verursacht und AV /
  SmartScreen den Silent-Install bei manchen Setups flaggt —
  aktivieren nur wenn du Lively wirklich mitinstalliert haben
  willst. User die Lively schon haben (oder lieber separat aus dem
  MS Store installieren) lassen das aus.
- ☑ **Wallpaper Engine** (Steam — automatisch übersprungen wenn
  nicht erkannt) — kopiert das einzige zusammengeführte
  `signalrgb-glow/`-Bundle nach
  `…\steamapps\common\wallpaper_engine\projects\myprojects\`. In WE
  einmal pro Monitor zuweisen und pro Zuweisung einen anderen
  *Screen index* wählen.

**Zusätzliche Einrichtung:**

- ☑ **SignalRGB Desktop Wallpaper Plugin installieren**
  *(erforderlich)* — legt `SignalRGB_Desktop_Wallpaper.js` + `.qml`
  in deinen `Documents\WhirlwindFX\Plugins\`-Ordner. Ohne das hat
  SignalRGB keinen Weg, Farben an die Bridge zu schicken und das
  ganze Produkt macht nichts. Nur deaktivieren wenn du die
  Plugin-Datei von Hand pflegst (nur für Entwickler).
- ☑ **Bridge automatisch beim Login starten** — fügt einen HKCU
  `Run`-Registry-Eintrag hinzu. Standard-Autostart pro User, kein
  Dienst.
- ☑ **Configurator am Ende im Browser öffnen** — öffnet die
  In-Browser-Einstellungs-UI direkt nach dem Install, damit du einen
  Hintergrund wählen und konfigurieren kannst ohne erst das
  Tray-Icon zu suchen.

#### 4. Zusammenfassung

![Zusammenfassungs-Review](images/installer/04-summary.png)

Kurze Übersicht was gleich passiert. Auf *Installieren* klicken.

#### 5. (Optional) Laufende Bridge schließen

![File-in-use-Warnung](images/installer/05-file-in-use.png)

Erscheint nur bei einem Update wenn die Bridge noch läuft.
*Schließe die Anwendungen automatisch* wählen und der Installer
beendet den laufenden Prozess vor dem Überschreiben — spart das
manuelle Beenden + erneutes Ausführen. Die Bridge kann am Ende des
Wizards via *Jetzt starten*-Checkbox automatisch wieder gestartet
werden.

#### 6. Fertig

![Letzte Seite mit Post-Install-Aktionen](images/installer/06-finished.png)

Zwei Opt-in-Aktionen am Ende:

- ☑ **SignalRGB Wallpaper Bridge jetzt starten** — startet
  `SignalRGBBridge.exe`, das Tray-Icon erscheint sofort. Wenn
  deaktiviert, kannst du sie später auch über das Startmenü starten.
- ☑ **Configurator im Browser öffnen** — öffnet
  `http://127.0.0.1:17320/configurator`, damit du Hintergrund, Glow,
  Widget-Einstellungen etc. anpassen kannst.

> Eine dritte Checkbox erscheint nur wenn **Wallpaper Engine gewählt
> wurde UND Steam nicht erkannt wurde**: *Wallpaper-Engine-Bundle-
> Ordner öffnen*. In dem Fall hat der Installer `signalrgb-glow/`
> nach `{app}\Wallpaper Engine wallpapers\` statt in Steams
> `myprojects\` gelegt, und du musst den Ordner von Hand in
> Wallpaper Engine ziehen. Sobald Steam erkannt wird, landet das
> Bundle direkt am richtigen Ort und keine Post-Install-Aktion ist
> nötig.

### Nach dem Install

Der Installer öffnet die Ordner die der Auto-Import übersprungen hat
(für manuelles Nachholen) und startet die Bridge wenn *"Jetzt
starten"* aktiv blieb. Die Bridge lebt im System-Tray als kleines
Monitor-Icon mit fünf RGB-Pads darunter. Anklicken für den Eintrag
**Configurator…** — das ist die neue In-Browser-Einstellungs-UI für
alles (Hintergründe pro Bildschirm, Glow-Layout, Widgets, Effekte,
Parallax, …). Siehe [`tray-settings.md`](tray-settings.md) für alles
was das Tray-Menü kann, und den Abschnitt
[Configurator](#3-der-configurator) unten für den
Haupt-Einstellungs-Flow.

## Manueller Weg (ohne Installer)

Wenn du den Installer nicht ausführen willst:

| Datei | Wohin sie kommt | Größe |
| --- | --- | --- |
| `SignalRGBBridge.exe` | Beliebiger stabiler Ort (z. B. `C:\Tools\SignalRGBWallpaper\`) | ~20 MB |
| `SignalRGB_Desktop_Wallpaper.js` | `Documents\WhirlwindFX\Plugins\` | ~20 KB |
| `SignalRGB_Desktop_Wallpaper.qml` | gleicher Ordner | ~3 KB |
| `SignalRGB_Glow_Screen{1,2,3,4}.zip` | Jede einzeln auf Lively ziehen | ~100 KB jeweils |
| `SignalRGB_Glow_WE_Single.zip` | Entpacken; `signalrgb-glow/` in Steams `…\steamapps\common\wallpaper_engine\projects\myprojects\` legen. In WE einmal pro Monitor zuweisen, pro Zuweisung einen anderen *Screen index* in WEs Properties wählen. | ~300 KB |

Dann `SignalRGBBridge.exe` doppelklicken.

> **OneDrive-Hinweis:** Wenn dein Documents-Ordner über OneDrive
> synchronisiert ist, ist der tatsächliche Pfad
> `%USERPROFILE%\OneDrive\Dokumente\WhirlwindFX\Plugins\` (deutsches
> Windows) oder `OneDrive\Documents\…`. SignalRGB beobachtet den
> Pfad auf den du umgeleitet hast.

## Schritte im Detail

### 1. Plugin ist im WhirlwindFX-Ordner

SignalRGB lädt bei Dateiänderungen neu — die **Desktop Wallpaper -
Screen N**-Geräte sollten innerhalb weniger Sekunden in deiner
Geräteliste erscheinen. Wenn nicht:

- SignalRGB neu starten (Rechtsklick aufs Tray → Quit, dann neu
  starten).
- Prüfen ob die Dateien im richtigen Ordner gelandet sind (mit oder
  ohne OneDrive).
- Siehe [Fehlerbehebung → "Plugin erscheint nicht"](troubleshooting.md#plugin-erscheint-nicht).

### 2. Bridge läuft im System-Tray

Wenn du das Icon nicht siehst: Windows versteckt es vielleicht.
Rechtsklick auf die Taskleiste → Taskleisteneinstellungen → "Wählen
Sie aus, welche Symbole in der Taskleiste angezeigt werden" →
**SignalRGBBridge** aktivieren. Wenn der Prozess gar nicht läuft,
siehe [Fehlerbehebung → "Bridge startet nicht"](troubleshooting.md#bridge-startet-nicht).

### 3. Der Configurator

Rechtsklick aufs Tray-Icon → **Configurator…** (Default-Aktion). Ein
Browser-Tab öffnet `http://127.0.0.1:17320/configurator`. Tabs pro
Bildschirm oben, **vertikale Bereichs-Sidebar** links, und ein
**📺 Vorschau**-Toggle im Header der eine schwebende Live-Vorschau
des Wallpapers öffnet (unabhängig vom geöffneten Tab).

Die Sidebar teilt die Einstellungen in sechs Tabs:

- **Look** — Quick Looks, Hintergrund (mit Aktuelles-Bild-Thumbnail),
  Glow, und eine **Bildschirm-Layout**-Karte, in der Span- /
  Mirror-Setups für Ultrawides (die in Wahrheit zwei Monitore sind)
  konfiguriert werden.
- **Library** — durchsuchbares / sortierbares / nach Tags
  filterbares Wallpaper-Grid mit Rechtsklick-Kontextmenü (anwenden /
  drehen / spiegeln / anheften / löschen) und Live-Vorschau beim
  Hover.
- **Effekte** — Ambient-Preset-Kacheln (Schnee / Regen / Funken /
  Aurora mit Live-Mini-Canvas-Vorschau), Tint-Toggle, Dichte,
  PixelFX-Modus (Maus-Trail / Hover-Glow / Klick-Ripple / alle),
  3D-Parallax.
- **Widgets** — prominente Lock-Leiste oben, Drag-and-Resize-Layout-
  Vorschau darunter (Snap-to-Grid optional), Widget-Liste mit
  *Konfigurieren* + *Entfernen* pro Typ, Widget-Picker-Grid zum
  Hinzufügen.
- **Integrationen** — System (Bridge-Toggles + Wartung) bleibt
  offen; OpenRGB-Ausgabe, OpenRGB-SDK-Server, Farbquelle pro
  Bildschirm, sACN / E1.31, MQTT, REST-API, Plugins jeweils in
  eigenen aufklappbaren Blöcken.
- **System** — Voreinstellungen, Profile pro App,
  Sicherung / Wiederherstellung, Bildschirmanzahl-Picker.

Einstellungen werden sofort per WebSocket ans Live-Wallpaper
gepusht — kein Lively-Reload nötig.

Für die Bildschirmanzahl selbst: den **System**-Tab im Configurator
öffnen — die *Bildschirme*-Karte hat einen **1 / 2 / 3 / 4**-Picker.
Das SignalRGB-Plugin pollt die Bridge regelmäßig und passt seine
Geräteliste entsprechend an.

### 4. SignalRGB-Geräte auf der Leinwand platzieren

SignalRGB → Layouts öffnen. Für jedes *Desktop Wallpaper - Screen N*
Gerät das Gerät auf die Position auf der Leinwand ziehen, von der es
samplen soll. Typische Layouts:

- **Einzelmonitor:** Gerät zentrieren, so skalieren dass es die
  Leinwand ausfüllt.
- **Zwei Monitore (links + rechts):** Screen 1 auf die linke Hälfte,
  Screen 2 auf die rechte.
- **Drei Monitore:** Leinwand in Drittel teilen.

Optional **Glow Grid Base Size** in den Plugin-Einstellungen bis auf
`128` hochsetzen — die Bridge chunked jeden Frame > 4 KB
transparent auf mehrere Datagramme. 32 / 36 / 64 / 96 / 128 sind
alle gültig; größer = feinerer Glow-Gradient + mehr Browser-Arbeit.

Für **Ultrawide-Monitore** (21:9 / 32:9 oder alles nicht-quadratische)
das **Aspect Ratio** des Plugins auf *Auto* setzen (Default) — die
Bridge meldet den tatsächlichen Viewport pro Bildschirm über `GET
/config`, und das Plugin leitet daraus die längere Seite des
Glow-Grids ab. Ein 3840 × 1080 Monitor bei Base Size 32 sendet so
ein 114 × 32 Grid statt eines quadratischen 32 × 32, das seine
Breite unter-samplen würde. Die anderen Optionen erzwingen eine
feste Form (*1:1* / *16:9* / *21:9* / *32:9* / *9:16*) oder
erlauben *Custom Cols × Rows* direkt einzutippen. Siehe
[`multi-screen-setup.md`](multi-screen-setup.md) für ein
durchgerechnetes Beispiel.

### 5. Wallpaper zuweisen

**Lively-User:** Wenn du den Auto-Import zugelassen hast, hat deine
Library bereits *SignalRGB Glow - Screen 1 / 2 / 3 / 4*-Kacheln.
Jede rechtsklicken → *Als Wallpaper setzen* → passenden Monitor
wählen.

Wenn du nicht auto-importiert hast, jede `SignalRGB_Glow_ScreenN.zip`
auf Lively ziehen, dann zuweisen.

**Wallpaper-Engine-User:** Wenn du Auto-Copy zugelassen hast, listet
WE bereits **SignalRGB Glow** unter *My Wallpapers* — eine Kachel
die du jedem Monitor zuweist den du nutzen willst. In den Properties
jeder Zuweisung einen anderen *Screen index* (Screen 1 / 2 / 3 / 4)
wählen, damit die Bridge die Farben des passenden SignalRGB-Geräts
schickt.

Wenn du nicht auto-kopiert hast, `SignalRGB_Glow_WE_Single.zip`
entpacken und den `signalrgb-glow`-Ordner nach
`…\steamapps\common\wallpaper_engine\projects\myprojects\` legen.

## Nächste Schritte

- [Tray-Einstellungen-Referenz](tray-settings.md) — was jeder Menü-Eintrag tut
- [Multi-Monitor-Einrichtung](multi-screen-setup.md) — Leinwand-Platzierung-Walkthrough
- [Glow-Wallpaper bauen](building-wallpapers.md) — mit dem
  In-Browser-Builder transparente Regionen schneiden
- [Fehlerbehebung](troubleshooting.md) — wenn etwas nicht funktioniert

## Deinstallation

**Via Installer:** Windows-Einstellungen → Apps → SignalRGB Desktop
Wallpaper → Deinstallieren. (Oder `unins000.exe` im Install-Ordner.)

Der Uninstaller:

- Beendet die laufende Bridge zuerst (`taskkill /f /im SignalRGBBridge.exe`).
- Entfernt die Bridge-EXE + mitgelieferte Dateien aus `{InstallDir}`.
- Entfernt die auto-importierten Lively-Ordner
  (`signalrgb-glow-screen-{1,2,3,4}\`) wenn Lively erkannt wurde —
  lässt andere Lively-Wallpaper in Ruhe.
- Entfernt das auto-kopierte Wallpaper-Engine-Bundle
  (`signalrgb-glow\`, plus die alten `SignalRGB_Glow_Screen{1..4}\`-
  Ordner für User die von pre-0.7.2-beta updaten) wenn Steam
  erkannt wurde — lässt andere WE-Wallpaper in Ruhe.
- Löscht den Autostart-`Run`-Registry-Eintrag.

Das Plugin in `WhirlwindFX\Plugins\` wird *nicht* automatisch
entfernt — von Hand löschen wenn SignalRGB es vergessen soll.

**Manuelle Installation:** die manuellen Schritte rückwärts machen.
Die Bridge schreibt ihre Config nach
`%LOCALAPPDATA%\SignalRGBWallpaper\config.json` — den Ordner löschen
um die gespeicherten Einstellungen zu verwerfen.
