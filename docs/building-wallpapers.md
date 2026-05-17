# How to Build a Glow Wallpaper

The whole effect hinges on **transparent regions** in your background
image. Wherever the image is fully transparent (or partly transparent),
the SignalRGB glow shines through. Wherever it's opaque, you just see
the image — no glow.

This guide walks you through making your own from a regular wallpaper.

## The concept in one picture

```text
   ┌──────────────────────────────────────────┐
   │  Background image (your PNG with alpha)  │  ← top layer
   │   ▓▓▓▓▓▓▓▓░░░░░░▓▓▓▓░░░▓▓▓▓▓▓▓▓▓        │
   │   ▓▓▓▓▓▓▓▓░░░░░░▓▓▓▓░░░▓▓▓▓▓▓▓▓▓        │   ░ = transparent ("cut-out")
   │   ▓▓▓▓▓▓▓▓░░░░░░▓▓▓▓░░░▓▓▓▓▓▓▓▓▓        │   ▓ = opaque
   └──────────────────────────────────────────┘
                       │
                       │  alpha pixels pass through
                       ▼
   ┌──────────────────────────────────────────┐
   │  Glow layer (CSS grid driven by RGB)     │  ← bottom layer
   │   ████████████████████████████████████   │
   │   ████████████████████████████████████   │  Whatever colour
   │   ████████████████████████████████████   │  SignalRGB is sending
   └──────────────────────────────────────────┘
```

The image and the glow are stacked: image on top, glow behind. The
SignalRGB colours only show through wherever the image is transparent.

## Picking a source image

What works **well**:

- **Night-time / dark scenes** with bright windows, neon, signs,
  traffic lights, screens. Those bright spots become your glow zones.
- **Cyberpunk, vaporwave, synthwave art** — usually already has
  high-contrast bright areas suitable for cut-out.
- **Cityscapes at night** (skylines, alleys, train stations).
- **Sci-fi spaceship interiors** with control panels and lit edges.
- **Anime/illustration art** with stylised lighting — clean edges that
  are easy to cut out.

What works **poorly**:

- Photos of nature, mountains, beaches — no obvious cut-out candidates,
  glow ends up in arbitrary places.
- Bright daylight photos — nothing distinctly "glowy" to mask out.
- Very busy compositions — glow becomes muddy / hard to perceive.
- Images with already-transparent backgrounds (logo-style PNGs) — the
  glow fills the entire transparent area, looking flat.

### Resolution

Match your monitor resolution for best results (typically 1920×1080,
2560×1440, or 3840×2160). The wallpaper auto-scales but native is
sharpest. Multi-monitor: each monitor's wallpaper is independent — use
images sized for each.

### Where to find source images

Free / royalty-free sources:

- [Unsplash](https://unsplash.com/) — high-quality photos
- [Pexels](https://www.pexels.com/)
- [Pixabay](https://pixabay.com/)
- [Wallhaven](https://wallhaven.cc/) — wallpaper-specific, lots of
  digital art and cyberpunk content
- [Wallpaper Engine workshop](https://steamcommunity.com/app/431960/workshop/)
  — if you own WE, you can rip the source images out of bundles

Search terms that find good candidates: "cyberpunk city night",
"vaporwave room", "neon alley", "synthwave skyline", "spaceship
cockpit", "night street rain reflection".

## GIMP workflow (recommended — free, cross-platform)

GIMP is the canonical free image editor. Download from
[gimp.org](https://www.gimp.org/) — Windows installer is ~250 MB.

### 1. Open your image

`File → Open…` → pick your wallpaper image.

If it's a JPG (no alpha channel), the title bar won't say "(imported)"
but you still need step 2 before transparency works.

### 2. Add an alpha channel

`Layer → Transparency → Add Alpha Channel`

If the menu item is greyed out, the layer already has alpha. Skip.

### 3. Select the regions you want to cut out

Two main techniques — pick whichever fits your image:

**A) Select by Color** (best for clean, distinct bright areas)

1. Press `Shift+O` (or `Select → By Color…` from the menu).
2. Click on a bright pixel you want to cut out (e.g. a window).
3. In the tool options panel, adjust **Threshold** — higher = more
   similar colours get selected. Start at ~30, tweak until just the
   right areas are highlighted (you'll see the marching-ants outline).
4. If you missed a colour variant, hold `Shift` and click another
   bright area to add to the selection.

**B) Fuzzy Select / Magic Wand** (best for irregular shapes)

1. Press `U` (or `Select → Fuzzy Select`).
2. Click inside one region you want to cut out.
3. Hold `Shift` and click other regions to add them.
4. Threshold works the same way.

**C) Free Select / Lasso** (best for arbitrary shapes)

1. Press `F` (or `Select → Free Select`).
2. Click around the outline of the region. Double-click to close.
3. Multiple regions: hold `Shift` to add another lasso.

### 4. Soften the selection edges (optional but recommended)

Hard edges look pixelated when the glow blurs through. Feather them:

`Select → Feather…` → 2–4 pixels usually looks natural.

### 5. Delete the selected pixels

Press **Delete** (or `Edit → Clear`). The selected pixels turn into a
chequered pattern — that's transparency.

If you accidentally deleted too much: `Edit → Undo` (Ctrl+Z).

### 6. Repeat for additional regions

Switch back to the select tool and pick the next colour / area. Each
delete adds more cut-outs.

### 7. Preview

In GIMP, the chequered pattern shows transparency. To see roughly what
the glow will look like:

1. `Layer → New Layer…` → set Fill type to "Solid color".
2. Pick a bright magenta or cyan.
3. `Layer → Stack → Lower to Bottom`.
4. Now your image sits on top of a solid colour — the cut-outs show
   the magenta beneath. Multiply that mentally by "SignalRGB colours
   changing every frame" and you've got the wallpaper effect.

Delete the colour layer before exporting (or it will be in the PNG).

### 8. Export as PNG

`File → Export As…` → name it (e.g. `cyberpunk-night.png`) → click
**Export** → in the PNG options leave defaults → **Export**.

**Do not** use `File → Save` — that writes GIMP's native `.xcf` format
which the wallpaper can't load. Always use **Export As → PNG**.

### 9. Test in the wallpaper

1. Right-click the SignalRGB Wallpaper tray icon → **Settings…**
2. Pick the screen tab you want to apply it to.
3. **Background image** → Browse → pick your PNG.
4. Click **Save**. The wallpaper page applies it instantly.

Iterate: if too little glows, go back to GIMP and cut more out. Too
much, undo some deletions. Re-export, re-pick.

## Alternative tools

**Photopea** — free browser-based, GIMP-equivalent UI. Same workflow:
`Layer → Add Layer Mask` (or just use the eraser tool with a clean
background). Export as PNG. <https://www.photopea.com/>

**Photoshop** — `Layer → Layer Mask → Reveal All`, then paint black
over areas you want transparent. Export with `File → Export → Export
As… → PNG`.

**Krita** — similar to GIMP but more painter-oriented. Same Add Alpha →
Select → Delete workflow.

**ImageMagick / batch** — for power users, you can drop bright pixels
with a single command:

```powershell
magick input.jpg -alpha set -channel A `
  -evaluate set 0 -fuzz 30% `
  -fill none -opaque "#fff" `
  output.png
```

(Replace `#fff` with the colour to remove; `fuzz` is the tolerance.)

## What looks good — practical tips

- **Bigger transparent areas glow stronger.** Tiny single-pixel
  windows show almost nothing. Aim for at least 20×20 px holes.
- **Edges glow most.** The glow is blurred behind the image, so the
  outline of each transparent area gets a soft halo. Sharp jagged
  cut-outs look pixelated; feathered/anti-aliased look smooth.
- **Don't over-cut.** Leaving most of the image opaque keeps the
  composition recognisable. ~10–30% of the area transparent is a good
  starting range.
- **Cluster cut-outs.** A row of bright windows on a building works
  better than one window per face of the building — the glow becomes
  visible as a *region* rather than a single point.
- **Match cut-outs to your SignalRGB effect.** If your SignalRGB
  effect is a side-to-side sweep, a building skyline with windows
  along the bottom highlights the sweep nicely. If it's a rainbow
  cycle, anything with multiple separated bright spots works.
- **Test with the "Glow Strength" slider** in tray Settings if your
  glow feels weak. 150% gives a more dramatic look on dark
  backgrounds; 80–100% is more subtle.

## Example: the bundled cyberpunk skyline

The default background in `wallpaper_bridge/wallpaper/images/cyberpunk_skyline.svg`
is an SVG with hand-placed transparent rectangles for windows. Open it
in GIMP or Inkscape and you'll see how the windows are arranged. Use
it as a template if you want to author SVG-based wallpapers directly.

## Sharing your wallpapers

PNGs you create are yours to use however you like — they're not
distributed with this project. If you make something nice, feel free
to share in [Discussions on the repo](https://github.com/Delido/signalrgb-wallpaper/discussions).
