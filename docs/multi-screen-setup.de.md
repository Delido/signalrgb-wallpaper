# Multi-Monitor-Einrichtung

Glow auf 2, 3 oder 4 Monitoren unabhängig steuern. Jeder Monitor
kriegt sein eigenes SignalRGB-Gerät, seine eigene Canvas-Platzierung,
und sein eigenes Hintergrundbild + Layout im Configurator.

## Konzept

```text
                 SignalRGB Canvas
   ┌───────────────────────────────────────────┐
   │                                           │
   │   ┌─────────┐         ┌─────────┐         │
   │   │ Screen1 │         │ Screen2 │         │
   │   │  device │         │  device │         │
   │   └─────────┘         └─────────┘         │
   │                                           │
   └───────────────────────────────────────────┘
        │                       │
        │ UDP-Frames            │ UDP-Frames
        │ mit screen=0          │ mit screen=1
        ▼                       ▼
   ┌────────────────────────────────────┐
   │      SignalRGBBridge.exe           │
   │   routet per Screen-Index-Byte     │
   └────────────────────────────────────┘
        │                       │
        │ ws://...?screen=0     │ ws://...?screen=1
        ▼                       ▼
   ┌─────────┐             ┌─────────┐
   │ Monitor │             │ Monitor │
   │   1     │             │   2     │
   │ Lively  │             │ Lively  │
   │ Screen1 │             │ Screen2 │
   │  .zip   │             │  .zip   │
   └─────────┘             └─────────┘
```

Drei unabhängige Teile müssen aufeinander passen:

1. **SignalRGB-Plugin** muss N Geräte announcen (gesteuert via
   *Bildschirme*-Picker im Configurator, rechts oben in der
   Tab-Leiste).
2. **SignalRGB-Canvas** muss diese Geräte dort platziert haben wo du
   Farben sampeln willst.
3. **Wallpaper-Host** (Lively oder Wallpaper Engine) muss den
   passenden Wallpaper-Zip / das Bundle auf jedem physikalischen
   Monitor zeigen. Für Lively ein Zip pro Bildschirm; für Wallpaper
   Engine entweder die Pro-Bildschirm-Bundles ODER das einzige
   kombinierte Bundle mit seinem *Screen index*-Property (v0.7.0+).

## Walkthrough: 2 Monitore

Ziel: Monitor 1 zeigt die linke Hälfte deines SignalRGB-Effekts,
Monitor 2 zeigt die rechte Hälfte.

### Schritt 1 — Bildschirmanzahl auf 2 setzen

Configurator öffnen (Tray-Icon → **Configurator…**). Rechts oben in
der Tab-Leiste ist ein *Bildschirme*-Picker — auf **2** klicken.

SignalRGB-Geräteliste zeigt jetzt:
- Desktop Wallpaper - Screen 1
- Desktop Wallpaper - Screen 2

(Screen 3 verschwindet entweder oder hat nie existiert wenn du bei 1
angefangen hast.)

### Schritt 2 — Geräte auf der SignalRGB-Canvas platzieren

SignalRGB → Layouts öffnen (die Canvas-Ansicht). Beide Geräte
draufziehen:

- **Screen-1-Gerät** — auf die **linke Hälfte** der Canvas
  positionieren. Größe so wählen dass es genau die Fläche bedeckt
  die du für Monitor 1 sampeln willst.
- **Screen-2-Gerät** — auf die **rechte Hälfte**, gespiegelt.

Tipp: SignalRGBs Grid-Alignment-Tools nutzen damit die beiden Geräte
gleich groß und sauber ausgerichtet sind — sonst sieht Asymmetrie
zwischen deinen Monitoren komisch aus.

Wenn du willst dass jeder Monitor den GANZEN Effekt sieht (gespiegelt),
einfach beide Geräte übereinander auf die volle Canvas legen. Sie
kriegen die gleichen Farben und deine beiden Monitore sehen identisch
aus (nicht sehr nützlich außer du hast einen bestimmten Grund).

### Schritt 3 — Wallpaper zuweisen

**Lively:** Wenn du den Auto-Import zugelassen hast (Default),
sind *SignalRGB Glow - Screen 1 / 2* bereits in deiner Lively-
Library unter deterministischen Ordnern. Jede rechtsklicken →
*Als Wallpaper setzen* → passenden Monitor wählen. Wenn du nicht
auto-importiert hast, jede `SignalRGB_Glow_ScreenN.zip` erst auf
Lively ziehen.

**Wallpaper Engine:** entweder die Pro-Bildschirm-Items abonnieren /
nutzen (*SignalRGB Glow - Screen 1 / 2*) und jedem seinen Monitor
zuweisen, oder das **einzige kombinierte Item** nutzen (empfohlen):
das gleiche Wallpaper jedem Monitor zuweisen und in WEs Properties
pro Zuweisung einen anderen *Screen index* setzen. Beide Wege
verbinden sich mit dem passenden `?screen=N` an der Bridge.

**Wichtig:** Die *Zahl* in der Kachel / Property entspricht welchem
SignalRGB-Gerät das Wallpaper subscribt, nicht welchem physikalischen
Monitor es zugewiesen werden muss. Die zwei sind unabhängig — du
entscheidest das Mapping über welchen Host-Monitor du es aktivierst.

### Schritt 4 — Verifizieren

Jedes Wallpaper sollte jetzt mit einem Teil deines SignalRGB-Effekts
leuchten. SignalRGB-Effekte wechseln um sicherzustellen dass die
Farben mitziehen.

Wenn ein Wallpaper schwarz bleibt:

- *Debug-Overlay anzeigen* im Configurator → Tab des Bildschirms →
  *Hintergrund*-Bereich aktivieren — wenn das Overlay auf dem
  Wallpaper `connecting` oder `disconnected` sagt, läuft die Bridge
  nicht oder ihr WS-Handshake schlägt fehl. Siehe
  [troubleshooting.md](troubleshooting.md).
- Sicherstellen dass das passende SignalRGB-Gerät auf der Canvas an
  einer nicht-leeren Stelle liegt. Ein Gerät ohne Canvas-Platzierung
  bekommt nur schwarze Pixel.

## Walkthrough: 3 Monitore

Wie oben aber mit *Bildschirme = 3* und drei Zips. Canvas-Layout-
Vorschläge:

- **3 in Reihe:** Canvas in vertikale Drittel teilen, ein Gerät pro
  Drittel.
- **2+1 (z. B. zwei Haupt- + ein vertikaler Seitenmonitor):** Screen
  1 und Screen 2 nebeneinander den Großteil der Canvas abdecken
  lassen, Screen 3 als kleine Region wo's für den Seitenmonitor
  Sinn macht.

## Walkthrough: 4 Monitore

Gleicher Ablauf mit *Bildschirme = 4* und vier Zips / vier Zuweisungen
des einen WE-Bundles. Canvas-Layout-Vorschläge:

- **4 in Reihe:** Canvas in Viertel teilen, ein Gerät pro Viertel.
  Passt schön zu einem 4× super-wide Setup oder einer 1+3-Reihe.
- **2 × 2 Raster:** Quad-Monitor-Stapel (zwei oben, zwei unten).
  Screens 1/2 oben an der Canvas, Screens 3/4 unten. Jedes Gerät
  sampled ein Quadrant des Effekts.
- **3+1 (Haupt-Tripel + Seite):** Screens 1/2/3 decken den
  Haupt-Triple-Monitor-Block ab; Screen 4 lebt in einer kleinen
  dedizierten Region für den Seiten- / Portrait- / Steuermonitor.
- **Unabhängiges Pro-Monitor-Sampling:** alle vier Geräte
  übereinander auf die volle Canvas — jeder Monitor sieht den ganzen
  Effekt, gespiegelt. Einfachstes Layout wenn dir Spatial-Mapping
  egal ist.

Heads-up zum UDP-Durchsatz: bei 128 × 128 Grid × 4 Screens × ~30 fps
sind das ~49 KB pro Frame nach Chunking. Immer noch <2 MB/s auf
localhost (keine echte Last), aber die SignalRGB-Plugin-Sandbox läuft
auf einer Shared-Event-Loop — auf 64 × 64 oder 96 × 96 Grid runter
wenn der Plugin-Tick mal stottern sollte.

## Hintergrundbilder pro Bildschirm

Jeder Bildschirm-Tab im Configurator ist unabhängig. Du kannst:

- Ein anderes Hintergrund-PNG pro Monitor verwenden (z. B. jedes mit
  zum Monitor-"Thema" passenden Cut-Outs)
- Das gleiche PNG aber andere Layouts / Glow-Stärken
- Mischen: ein Wallpaper zeigt Pixel-Grid, ein anderes zeigt Pills

## Bildschirmanzahl später reduzieren

Wenn du Anzahl = 4 gesetzt hast und auf 2 (oder 3) zurück willst:

1. Configurator → rechts oben *Bildschirme*-Picker → neuen Wert
   wählen. Die Bridge persistiert das und pusht an jeden offenen
   Configurator-Tab.
2. Die jetzt-ungenutzten Screen-N-Geräte verschwinden aus SignalRGB.
   Ihre Canvas-Platzierung ist **weg** — Configurator-Einstellungen
   für die höher-indizierten Bildschirme bleiben in `config.json`,
   also stellt das Hochsetzen der Anzahl sie wieder her.
3. Die Wallpaper für die abgeworfenen Bildschirme bekommen keine
   Frames mehr und zeigen einen leeren Glow-Layer. Sie in Lively /
   Wallpaper Engine deaktivieren, sonst versuchen sie weiter den
   WS-Connect.
