# Glow-Wallpaper bauen

Der ganze Effekt hängt von **transparenten Regionen** in deinem
Hintergrundbild ab. Wo das Bild komplett transparent (oder teilweise
transparent) ist, scheint das SignalRGB-Glow durch. Wo es deckend
ist, siehst du nur das Bild — kein Glow.

Zwei Wege das zu machen:

1. **Der eingebaute Builder** (seit v0.3.0) — Tray-Icon → "Wallpaper
   bauen…" — siehe [nächster Abschnitt](#eingebauter-builder-der-schnelle-weg).
   Gut für ~80 % der Fälle: Bild wählen, helle Farben anklicken,
   speichern.
2. **GIMP** (oder ein anderer Editor mit Alpha + Auswahl) — volle
   Kontrolle, unregelmäßige Formen, weiche Pinsel — siehe
   [GIMP-Workflow](#gimp-workflow-volle-kontrolle).

## Eingebauter Builder (der schnelle Weg)

Die Bridge liefert einen kleinen canvas-basierten Bild-Editor mit, der
den "alle Pixel mit dieser Farbe entfernen"-Workflow inline macht,
kein externes Tool nötig.

### Schritte

1. Rechtsklick aufs **SignalRGB-Wallpaper-Tray-Icon** →
   **Wallpaper bauen…** (oder im Configurator unter *Hintergrund*
   auf **Builder öffnen…** klicken). Dein Default-Browser öffnet
   `http://127.0.0.1:17320/builder`.
2. Auf **Bild auswählen…** klicken (oder eine PNG/JPG/WebP-Datei in
   den Canvas-Bereich ziehen).
3. Das Bild erscheint auf einem Schachbrett-Hintergrund — das
   Schachbrett ist was durchscheint wo du Pixel transparent machst.
4. Den **Toleranz**-Slider justieren (Default 30) — höher = ein
   einzelner Klick entfernt einen breiteren Bereich ähnlicher Farben.
5. **Auf einen hellen Pixel** im Canvas klicken (z. B. ein Fenster in
   einem Hochhaus, ein Neonschild). Jeder Pixel innerhalb der
   Toleranz wird transparent. Mehr Stellen anklicken um mehr Farben
   zu entfernen; jeder Klick wird in der Sidebar geloggt.
6. Den Toleranz-Slider NACH einem Klick anpassen wendet live neu an,
   damit du die richtige Toleranz für den jüngsten Pick einstellen
   kannst.
7. Die **Kanten weichzeichnen (2 px Feather)**-Checkbox ist Default
   an — verhindert dass transparente Kanten pixelig aussehen wenn
   das Glow durchschimmert.
8. **Rückgängig** entfernt den letzten Klick, **Zurücksetzen** fängt
   von vorne an.
9. **Als PNG speichern** lädt via Browser als
   `<original-name>-glow.png` runter, oder den **Anwenden ▾**-Button
   in der Canvas-Toolbar (rechts oben) klicken um direkt auf einen
   gewählten Bridge-Bildschirm zu pushen — auf einen einzelnen
   Bildschirm gestreckt, oder über einen Span verteilt wenn die
   Quell-Aspect-Ratio passt. Anwenden legt auch eine Kopie in deine
   Library damit du später re-applizieren kannst ohne neu zu
   bearbeiten.
10. (Nur Download-Weg) Tray-Icon → **Configurator…** → den
    Bildschirm-Tab wählen → *Hintergrund* → *Bild auswählen…* →
    deine neue PNG wählen. Die Bridge speichert sie unter
    `%LOCALAPPDATA%\SignalRGBWallpaper\screens\` und pusht die neue
    URL ans Live-Wallpaper.

Das war's. Das Wallpaper aktualisiert live auf allen Monitoren die
diesen Screen-Index zeigen — kein Host-Reload.

### Monitor-Wall-Modus (Multi-Tile)

Der **Monitor-Wand**-Bereich rechts macht aus dem Builder einen
Tile-basierten Composer statt einer einzelnen Canvas:

- Jeder Bridge-Bildschirm wird zu einem oder mehreren Tiles (ein
  Span-Layout produziert ein Tile pro physikalischem Monitor — jedes
  Tile zeigt die Hälfte / Viertel des Bildes das dieser Bildschirm
  tatsächlich rendern würde).
- Auf ein leeres Tile klicken um nur in dieses Tile ein Bild zu laden
  (Datei-Picker / Library / aktuelle Canvas / aktueller
  Bildschirm-Hintergrund).
- Auf ein gefülltes Tile klicken und *Im Haupteditor öffnen* wählen
  um den Slot im Editor zu öffnen; **In Slot speichern** überträgt
  die Änderungen zurück.
- Ein Panorama auf ein Span-Tile ziehen und der Builder bietet
  **über den Span verteilen** an — ein Slice pro Monitor, sauber
  zugeschnitten.
- **Wand anwenden** klicken um jedes gestaged Tile in ein PNG pro
  Bridge-Bildschirm zu komponieren und an die Bridge zu pushen.

### Tipps für den Builder

- Die Canvas behält die **Original**-Pixel im Speicher —
  Rückgängig oder Toleranz-Änderung verliert nie kumulativ Daten.
- Klick auf einen bereits-transparenten Pixel ist ein No-Op (wir
  sampeln vom unberührten Original, nicht vom aktuellen Display).
- Out-of-the-box samplet der Klick den GENAUEN angeklickten Pixel.
  Wenn du versehentlich einen leicht-abweichenden Pixel triffst,
  Toleranz hochsetzen um den tatsächlichen Bereich abzudecken.
- Für sehr feine Arbeit (z. B. nur eine Fensterscheibe entfernen
  ohne einen ähnlich gefärbten Schatten auf dem Dach) GIMP nutzen —
  der Builder macht globalen Farb-Match, nicht räumlich.

## Das Konzept in einem Bild

```text
   ┌──────────────────────────────────────────┐
   │  Hintergrundbild (deine PNG mit Alpha)   │  ← obere Lage
   │   ▓▓▓▓▓▓▓▓░░░░░░▓▓▓▓░░░▓▓▓▓▓▓▓▓▓        │
   │   ▓▓▓▓▓▓▓▓░░░░░░▓▓▓▓░░░▓▓▓▓▓▓▓▓▓        │   ░ = transparent ("Cut-Out")
   │   ▓▓▓▓▓▓▓▓░░░░░░▓▓▓▓░░░▓▓▓▓▓▓▓▓▓        │   ▓ = deckend
   └──────────────────────────────────────────┘
                       │
                       │  Alpha-Pixel lassen durch
                       ▼
   ┌──────────────────────────────────────────┐
   │  Glow-Lage (CSS-Grid, von RGB getrieben) │  ← untere Lage
   │   ████████████████████████████████████   │
   │   ████████████████████████████████████   │  Welche Farbe auch
   │   ████████████████████████████████████   │  SignalRGB sendet
   └──────────────────────────────────────────┘
```

Bild und Glow sind übereinander gestapelt: Bild oben, Glow dahinter.
Die SignalRGB-Farben scheinen nur dort durch wo das Bild transparent
ist.

## Quellbild wählen

Was **gut** funktioniert:

- **Nacht- / dunkle Szenen** mit hellen Fenstern, Neon, Schildern,
  Ampeln, Bildschirmen. Diese hellen Stellen werden zu deinen
  Glow-Zonen.
- **Cyberpunk-, Vaporwave-, Synthwave-Art** — hat meistens schon
  kontrastreiche helle Bereiche die sich zum Cut-Out eignen.
- **Stadtsilhouetten bei Nacht** (Skylines, Gassen, Bahnhöfe).
- **Sci-Fi-Raumschiff-Innenräume** mit Steuerpanels und
  beleuchteten Kanten.
- **Anime- / Illustrations-Art** mit stilisierter Beleuchtung —
  saubere Kanten die sich leicht ausschneiden lassen.

Was **schlecht** funktioniert:

- Fotos von Natur, Bergen, Stränden — keine offensichtlichen
  Cut-Out-Kandidaten, Glow landet an beliebigen Stellen.
- Helle Tageslicht-Fotos — nichts klar "Glow-fähiges" zum
  Maskieren.
- Sehr unruhige Kompositionen — Glow wird matschig / schwer
  wahrnehmbar.
- Bilder mit bereits-transparenten Hintergründen (Logo-PNGs) — das
  Glow füllt den gesamten transparenten Bereich und wirkt flach.

### Auflösung

Für beste Ergebnisse Monitor-Auflösung matchen (typisch 1920×1080,
2560×1440 oder 3840×2160). Das Wallpaper skaliert automatisch, aber
nativ ist am schärfsten. Multi-Monitor: jedes Wallpaper pro Monitor
ist unabhängig — Bilder passend zu jedem nutzen.

### Wo Quellbilder finden

Kostenlose / lizenzfreie Quellen:

- [Unsplash](https://unsplash.com/) — hochwertige Fotos
- [Pexels](https://www.pexels.com/)
- [Pixabay](https://pixabay.com/)
- [Wallhaven](https://wallhaven.cc/) — wallpaper-spezifisch, viel
  Digital-Art und Cyberpunk-Content
- [Wallpaper-Engine-Workshop](https://steamcommunity.com/app/431960/workshop/)
  — wenn du WE besitzt, kannst du Source-Bilder aus Bundles ziehen

Suchbegriffe die gute Kandidaten finden: "cyberpunk city night",
"vaporwave room", "neon alley", "synthwave skyline",
"spaceship cockpit", "night street rain reflection".

## GIMP-Workflow (volle Kontrolle)

GIMP ist der kanonische kostenlose Bild-Editor — nutzen wenn der
"Pixel mit dieser Farbe entfernen"-Ansatz des Builders nicht
präzise genug ist (unregelmäßige Formen, weiche Pinsel, manuelles
Masking). Download auf [gimp.org](https://www.gimp.org/) —
Windows-Installer ist ~250 MB.

### 1. Bild öffnen

`Datei → Öffnen…` → dein Wallpaper-Bild wählen.

Wenn's eine JPG ist (kein Alpha-Channel), zeigt die Titelleiste zwar
nicht "(importiert)", aber du brauchst Schritt 2 trotzdem bevor
Transparenz funktioniert.

### 2. Alpha-Channel hinzufügen

`Ebene → Transparenz → Alphakanal hinzufügen`

Wenn der Menüpunkt ausgegraut ist, hat die Ebene schon Alpha.
Überspringen.

### 3. Die Regionen auswählen die du ausschneiden willst

Zwei Haupttechniken — die wählen die zu deinem Bild passt:

**A) Nach Farbe auswählen** (am besten für saubere, distinkte helle
Bereiche)

1. `Umschalt+O` drücken (oder `Auswahl → Nach Farbe…` aus dem
   Menü).
2. Auf einen hellen Pixel klicken den du ausschneiden willst
   (z. B. ein Fenster).
3. Im Werkzeug-Options-Panel **Schwellwert** justieren — höher =
   mehr ähnliche Farben werden ausgewählt. Bei ~30 anfangen,
   tunen bis genau die richtigen Bereiche markiert sind (die
   marching-ants Umrisslinie wird sichtbar).
4. Wenn eine Farbvariante übersehen wurde, `Umschalt` halten und
   einen anderen hellen Bereich anklicken um zur Auswahl
   hinzuzufügen.

**B) Zauberstab / Magic Wand** (am besten für unregelmäßige
Formen)

1. `U` drücken (oder `Auswahl → Magische Auswahl`).
2. Innen in eine Region klicken die du ausschneiden willst.
3. `Umschalt` halten und auf andere Regionen klicken um
   hinzuzufügen.
4. Schwellwert funktioniert gleich.

**C) Freie Auswahl / Lasso** (am besten für beliebige Formen)

1. `F` drücken (oder `Auswahl → Freie Auswahl`).
2. Um den Umriss der Region klicken. Doppelklick zum Schließen.
3. Mehrere Regionen: `Umschalt` halten um ein weiteres Lasso
   hinzuzufügen.

### 4. Auswahl-Kanten weichzeichnen (optional aber empfohlen)

Harte Kanten sehen pixelig aus wenn das Glow durchschimmert.
Weichzeichnen:

`Auswahl → Ausblenden…` → 2–4 Pixel sehen meistens natürlich aus.

### 5. Ausgewählte Pixel löschen

**Entf** drücken (oder `Bearbeiten → Löschen`). Die ausgewählten
Pixel werden zu einem Schachbrettmuster — das ist Transparenz.

Falls du versehentlich zuviel gelöscht hast:
`Bearbeiten → Rückgängig` (Strg+Z).

### 6. Für weitere Regionen wiederholen

Zurück zum Auswahl-Werkzeug und die nächste Farbe / Fläche wählen.
Jedes Löschen fügt weitere Cut-Outs hinzu.

### 7. Vorschau

In GIMP zeigt das Schachbrettmuster Transparenz. Um grob zu sehen
wie das Glow aussehen wird:

1. `Ebene → Neue Ebene…` → Fülltyp auf "Vordergrundfarbe" setzen.
2. Helles Magenta oder Cyan wählen.
3. `Ebene → Stapel → Nach ganz unten`.
4. Jetzt sitzt dein Bild über einer Farbfläche — die Cut-Outs
   zeigen das Magenta darunter. Multipliziere das gedanklich mit
   "SignalRGB-Farben die sich jeden Frame ändern" und du hast den
   Wallpaper-Effekt.

Die Farbebene vor dem Export löschen (sonst ist sie im PNG).

### 8. Als PNG exportieren

`Datei → Exportieren als…` → benennen (z. B. `cyberpunk-night.png`)
→ **Exportieren** klicken → bei den PNG-Optionen die Defaults
lassen → **Exportieren**.

**Nicht** `Datei → Speichern` benutzen — das schreibt GIMPs
natives `.xcf`-Format das das Wallpaper nicht laden kann. Immer
**Exportieren als → PNG**.

### 9. Im Wallpaper testen

1. Rechtsklick aufs SignalRGB-Wallpaper-Tray-Icon →
   **Configurator…**.
2. Den Bildschirm-Tab wählen auf den du es anwenden willst.
3. *Hintergrund* → *Bild auswählen…* → deine PNG wählen.

Die Wallpaper-Seite wendet es sofort an — kein Speichern-Button,
jede Configurator-Änderung pusht direkt per WebSocket ans
Live-Wallpaper.

Iterieren: wenn zu wenig leuchtet, zurück zu GIMP und mehr
ausschneiden. Zu viel, einige Löschungen rückgängig machen.
Re-Export, neu wählen.

## Alternative Tools

**Photopea** — kostenlos im Browser, GIMP-äquivalentes UI. Gleicher
Workflow: `Ebene → Ebenenmaske hinzufügen` (oder einfach den
Radierer auf sauberem Hintergrund). Als PNG exportieren.
<https://www.photopea.com/>

**Photoshop** — `Ebene → Ebenenmaske → Alles einblenden`, dann
schwarz über die Bereiche malen die transparent sein sollen. Mit
`Datei → Exportieren → Exportieren als… → PNG` exportieren.

**Krita** — ähnlich GIMP aber mehr Maler-orientiert. Gleicher
Add-Alpha → Auswahl → Löschen-Workflow.

**ImageMagick / Batch** — für Power-User kannst du helle Pixel mit
einem einzelnen Befehl entfernen:

```powershell
magick input.jpg -alpha set -channel A `
  -evaluate set 0 -fuzz 30% `
  -fill none -opaque "#fff" `
  output.png
```

(`#fff` durch die zu entfernende Farbe ersetzen; `fuzz` ist die
Toleranz.)

## Was gut aussieht — praktische Tipps

- **Größere transparente Bereiche leuchten stärker.** Winzige
  Einzelpixel-Fenster zeigen fast nichts. Mindestens 20×20 px
  Löcher anpeilen.
- **Kanten leuchten am stärksten.** Das Glow ist hinter dem Bild
  unscharf, also kriegt der Umriss jedes transparenten Bereichs
  einen weichen Heiligenschein. Scharf-gezackte Cut-Outs sehen
  pixelig aus; weichgezeichnete / antialiased sehen sanft aus.
- **Nicht über-schneiden.** Den größten Teil des Bildes deckend
  zu lassen erhält die Komposition erkennbar. ~10–30 % der Fläche
  transparent ist ein guter Startbereich.
- **Cut-Outs gruppieren.** Eine Reihe heller Fenster an einem
  Gebäude funktioniert besser als ein Fenster pro Gebäudeseite —
  das Glow wird als *Region* sichtbar statt als einzelner Punkt.
- **Cut-Outs zum SignalRGB-Effekt matchen.** Wenn dein
  SignalRGB-Effekt ein Side-to-Side-Sweep ist, hebt eine
  Gebäude-Skyline mit Fenstern entlang der Unterkante den Sweep
  schön hervor. Bei einem Regenbogen-Zyklus funktioniert alles mit
  mehreren separaten hellen Spots.
- **Mit dem *Stärke*-Slider testen** im *Glow*-Bereich des
  Configurators wenn dein Glow schwach wirkt. 150 % gibt einen
  dramatischeren Look auf dunklen Hintergründen; 80–100 % ist
  subtiler.

## Beispiel: Die mitgelieferten Essentials

Der Installer liefert sechs AI-generierte Cyberpunk- / Aurora- /
Forest- / Space- / Synthwave- / Crystal-Wallpaper unter
`installer/assets/library/` (4K WebP mit luminanz-basiertem Alpha).
Erstellt mit Juggernaut XL v9 + 4xNomos8kDAT in einem
ComfyUI-Workflow — siehe `installer/assets/library/IMAGES_NOTICE.md`
für die vollständige Provenienz- + Lizenz-Kette. In einem
RGBA-WebP-fähigen Bild-Editor öffnen um zu sehen wie die Alpha-Maske
gebakt wurde.

## Wallpaper teilen

PNGs die du erstellst gehören dir — sie werden nicht mit diesem
Projekt verteilt. Wenn du etwas Schönes machst, gerne in den
[Discussions im Repo](https://github.com/Delido/signalrgb-wallpaper/discussions)
teilen.
