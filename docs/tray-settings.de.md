# Tray-Icon-Referenz

Was jeder Eintrag im Tray-Menü der Bridge tut. Die Bridge selbst läuft
still im System-Tray (kleines Monitor-Icon mit fünf RGB-Pads
darunter); die ganze tägliche Arbeit passiert über den **Configurator**
der aus diesem Menü geöffnet wird.

Rechtsklick aufs Tray-Icon öffnet das Menü. Linksklick führt die
Default-Aktion aus (Configurator).

## Oberste Ebene

| Eintrag | Was er tut |
| --- | --- |
| **Configurator…** *(Default-Klick)* | Öffnet `http://127.0.0.1:17320/configurator` im Default-Browser. Haupt-UI — Tabs pro Bildschirm für Hintergrund / Glow / Effekte / Widgets, Drag-and-Resize-Layout-Vorschau, Live-Settings-Push zurück ans Wallpaper. Siehe [den Configurator-Abschnitt](#der-configurator) unten. |
| **Wallpaper bauen…** | Öffnet `http://127.0.0.1:17320/builder` — der In-Browser-Editor zum Schneiden transparenter Regionen aus beliebigen Bildern. Siehe [building-wallpapers.md](building-wallpapers.md). |
| **🔓 Sperren / 🔒 Entsperren Widgets (alle Bildschirme)** | Ein-Klick-Toggle der `widgetsLocked` auf jedem aktiven Bildschirm flippt. Spiegelt die Lock-Leiste oben im Widgets-Bereich des Configurators. Wenn entsperrt, lassen sich Widgets auf dem Live-Wallpaper *und* in der Configurator-Vorschau ziehen + größenändern. |
| **Erweitert** *(Untermenü)* | Power-User-Kram aus dem Default-Menü ausgelagert — siehe unten. |
| **Updates** *(Untermenü)* | In-App-Update-Checker + der "Beta-Versionen erlauben"-Toggle — siehe unten. |
| **Über…** | Standalone-Fenster mit Version, GitHub-Link, Maintainer + Avatar, Open-Source-Credits-Link und einem "Buy me a coffee"-PayPal-Button. |
| **Beenden** | Hard-Stoppt den Bridge-Prozess. Wallpaper-Seiten trennen sich; das SignalRGB-Plugin versucht weiter UDP zu schicken, aber keiner hört zu. EXE neu starten um fortzusetzen. |

Wenn ein neueres Release veröffentlicht ist, erscheint ein zusätzlicher
`⬆ Update verfügbar: vX.Y.Z — Release-Seite öffnen` Eintrag oben im
Menü.

## Erweitert-Untermenü

| Eintrag | Was er tut |
| --- | --- |
| **Widget schnell hinzufügen** *(Untermenü)* | Untermenü pro Bildschirm das das *Widget hinzufügen*-Picker-Grid des Configurators spiegelt. Gleiche elf Typen, plus *Widgets bearbeiten*-Toggle und eine "Aktuell platziert: N"-Status-Zeile. |
| **Schnelle Effekte** *(Untermenü)* | Untermenü pro Bildschirm mit Radio-Listen für Ambient-Preset (aus / Schnee / Regen / Funken / Aurora), Tint-mit-Glow-Toggle und PixelFX-Modus (aus / Trail / Glow / Ripple / alle). Gleicher State wie der Effekte-Bereich des Configurators. |
| **Config neu laden** | Liest `%LOCALAPPDATA%\SignalRGBWallpaper\config.json` neu von der Festplatte. Nützlich wenn du sie von Hand editiert hast oder Settings-Sync debugst. Pusht den neugeladenen State an alle verbundenen Wallpaper-Seiten. |

## Updates-Untermenü

| Eintrag | Was er tut |
| --- | --- |
| **Jetzt nach Updates suchen** | Manueller Trigger. Hits die GitHub-Releases-API; aktualisiert das Menü mit einem "Aktuell: vX.Y.Z — Release-Seite öffnen"-Eintrag wenn neuer. |
| **Update-Checks aktivieren** *(Checkbox)* | Master-Schalter (Default an). Wenn aus, ist die tägliche Hintergrund-Abfrage ausgesetzt. |
| **Beta-Versionen erlauben** *(Checkbox)* | Default aus. Wenn an, nehmen Prerelease-Tags am Vergleich teil. Semver-aware — `0.7.0-beta < 0.7.0`, also kriegen stabile User keinen Downgrade auf eine Beta. |
| Status-Zeile | Eine von: *Aktuell — zuletzt vor Xm geprüft* · *Aktuell: vX.Y.Z — Release-Seite öffnen* · *Letzte Prüfung fehlgeschlagen: …* · *Noch nicht geprüft*. |
| *Installiert: vX.Y.Z* | Read-Only-Anzeige der laufenden Bridge-Version. |

## Der Configurator

Der Configurator ist die In-Browser-UI ausgeliefert unter
`http://127.0.0.1:17320/configurator`. Tabs pro Bildschirm oben
(*Bildschirm 1 / 2 / 3 / 4* — nur die bis zu deiner Bildschirmanzahl
sind nützlich). Jeder Tab hat vier aufklappbare Bereiche.

### Hintergrund

| Steuerung | Was sie tut |
| --- | --- |
| Bildpfad | Direkter Pfad zu deinem Hintergrundbild (PNG / JPG / WebP / SVG). Editierbares Text-Feld — URL oder absoluten Pfad einfügen. |
| Bild auswählen… | Datei-Picker; die Bridge konvertiert zu PNG und speichert unter `%LOCALAPPDATA%\SignalRGBWallpaper\screens\screen-N-<timestamp>.png`. |
| Builder öffnen… | Öffnet den In-Browser-Builder in einem neuen Tab — zum Schneiden transparenter Regionen. |
| Fit | `cover` (zuschneiden zum Füllen — Default), `contain` (Letterbox), `fill` (strecken). |
| Abdunkeln | Schwarz-Overlay-Deckkraft, 0–100 %. Nützlich wenn ein helles Bild das Glow erschlägt. |

### Glow

| Steuerung | Was sie tut |
| --- | --- |
| Glow-Lage anzeigen | Master-an/aus für die SignalRGB-getriebene Glow-Lage. |
| Layout | Pixel-Grid (Default), vertikale Streifen, horizontale Streifen, zentrierte Pills, versteckt. |
| Stärke | Multiplikator für die Gesamt-Helligkeit/-Unschärfe des Glow, 0–200 %. |
| Grid-Unschärfe | Unschärfe-Radius in CSS-Pixeln für das Pixel-Grid-Layout (Default 30 px). Größer = sanfter / diffuser. |
| Streifen-Unschärfe | Gleiches für das Streifen-Layout (Default 60 px). |

### Effekte

| Steuerung | Was sie tut |
| --- | --- |
| Ambient-Preset | Fünf Kacheln: *Aus / Schnee / Regen / Funken / Aurora*. Jede außer *Aus* zeigt eine Live-Mini-Canvas-Vorschau die das tatsächliche Preset rendert. Klicken zum Anwenden. |
| Partikel mit Live-Glow-Farbe einfärben | Wenn an, folgen die Partikelfarben dem Live-SignalRGB-Feed-Durchschnitt. Default aus. |
| Dichte | 1–100, steuert Partikel-Anzahl / Sättigung. Default 60. |
| PixelFX (Cursor) | Maus-Trail / Hover-Glow / Klick-Ripple / alles kombiniert. Trail und Glow funktionieren unter Lively-Click-Through (Cursor-Position wird vom Host gepusht); Ripple braucht echte Klicks (*Wallpaper interaction* in Lively togglen). |
| 3D-Parallax | Hintergrundbild gleitet gegen den Cursor für einen Fake-Tiefen-Effekt, 0–120 px max. Verschiebung. 30 ≈ subtil, 80 ≈ dramatisch. Nutzt Livelys `livelyCurrentCursorPos` + DOM-mousemove-Fallback. |

### Widgets

| Steuerung | Was sie tut |
| --- | --- |
| Lock-Leiste | Großer Toggle oben mit farbigem Status-Punkt. Gesperrt = Read-Only; entsperrt = Drag + Resize aktiv auf dem Wallpaper *und* in der Layout-Vorschau. |
| Layout-Vorschau | Skaliertes Rechteck des Bildschirms (passt sich automatisch dem gemeldeten Viewport an, fällt auf 1920×1080 zurück wenn noch kein Wallpaper verbunden ist). Jedes Widget ist eine ziehbare + größenänderbare Box. Drop = persistiert via WebSocket. |
| Am Raster ausrichten | Toggle + Schritt-Picker (10 / 20 / 40 / 80 px). Wenn an, snappen Drag + Resize ans Grid und die Vorschau überlagert das Snap-Grid in Akzent-Blau. State persistiert in Browser-localStorage. |
| Widget-Liste | Zeilen pro Widget mit Icon + Label + Kurzbeschreibung. *Konfigurieren* öffnet ein Form-Modal (Options-Schema pro Typ, keine Prompts mehr). *Entfernen* löscht das Widget. |
| Widget hinzufügen | Picker-Grid mit allen elf registrierten Widget-Typen (Uhr, Kalender, Wetter, Notizzettel, Countdown, Bild, Zitat, CPU-Meter, RAM-Meter, Audio-Spektrum, Netzwerk — Netzwerk ist versteckt aber der Registry-Slot ist da). Klicken zum Hinzufügen an der Default-Position des Typs; das Widget erscheint sofort auf dem Live-Wallpaper. |

## Wo die Einstellungen liegen

- `%LOCALAPPDATA%\SignalRGBWallpaper\config.json` — Haupt-Config:
  Settings-Array pro Bildschirm, Bildschirmanzahl, Sprache,
  Update-Check-Flags. Bei jeder Einstellungs-Änderung aktualisiert.
- `%LOCALAPPDATA%\SignalRGBWallpaper\screens\screen-N-<timestamp>.png` —
  jedes Hintergrundbild das über den Configurator oder Builder
  hochgeladen wurde. Alte Timestamps werden beim nächsten Upload
  aufgeräumt.
- `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\SignalRGBWallpaperBridge` —
  Autostart-Eintrag (vom Installer gesetzt wenn der passende Task
  angekreuzt wurde). Mit dem Uninstaller entfernen oder den Wert von
  Hand löschen.

## Lokalisierung

Das ganze Tray-Menü + Über-Dialog respektieren den
**language**-Config-Key (`auto` / `en` / `de`). `auto` (Default)
wählt aus deinem Windows-Locale. Override per `config.json`-Edit:

```json
"language": "de"
```

Der Configurator nimmt die aktive Sprache beim ersten WebSocket-Push
von der Bridge auf und re-lokalisiert live ohne Reload.

Builder-Fenster-Strings sind seit v0.7.4-beta auch DE / EN; sie holen
die aktive Sprache aus dem `GET /config`-Endpoint der Bridge beim
Laden und wenden sie auf alle Labels + Toast-Nachrichten an.
