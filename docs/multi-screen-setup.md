# Multi-Screen Setup

Driving glow on 2, 3, or 4 monitors independently. Each monitor gets
its own SignalRGB device, its own canvas placement, and its own
background image + layout in the Configurator.

## Mental model

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
        │ UDP frames            │ UDP frames
        │ tagged screen=0       │ tagged screen=1
        ▼                       ▼
   ┌────────────────────────────────────┐
   │      SignalRGBBridge.exe           │
   │   routes by screen-index byte      │
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

Three independent pieces have to line up:

1. **SignalRGB plugin** must announce N devices (controlled via the
   Configurator's *Screens:* picker, top-right of the tab bar).
2. **SignalRGB canvas** must have those devices placed where you want
   colours sampled.
3. **Wallpaper host** (Lively or Wallpaper Engine) must show the
   matching wallpaper zip / bundle on each physical monitor. For
   Lively it's one zip per screen; for Wallpaper Engine you can use
   the per-screen bundles OR the single combined bundle with its
   *Screen index* property (v0.7.0+).

## Walkthrough: 2 monitors

Goal: monitor 1 shows the left half of your SignalRGB effect, monitor 2
shows the right half.

### Step 1 — set screen count to 2

Open the Configurator (tray icon → **Configurator…**). At the
top-right of the tab bar there's a *Screens:* picker — click **2**.

SignalRGB device list now shows:
- Desktop Wallpaper - Screen 1
- Desktop Wallpaper - Screen 2

(Screen 3 either disappears, or never existed if you started at 1.)

### Step 2 — place the devices on the SignalRGB canvas

Open SignalRGB → Layouts (the canvas view). Drag both devices onto it:

- **Screen 1 device** — position it at the **left half** of the canvas.
  Resize so it covers exactly the area you want sampled for monitor 1.
- **Screen 2 device** — position it at the **right half**, mirrored.

Tip: use SignalRGB's grid alignment tools to make the two devices the
same size and lined up — otherwise asymmetry between your monitors will
look weird.

If you want each monitor to see the WHOLE effect (mirrored), just place
both devices on top of each other covering the full canvas. They'll get
the same colours and your two monitors will look identical (not very
useful unless you have specific reasons).

### Step 3 — assign the wallpapers

**Lively:** if you let the installer auto-import (default on),
*SignalRGB Glow - Screen 1 / 2* are already in your Lively Library
under deterministic folders. Right-click each → *Set as wallpaper* →
pick the matching monitor. If you didn't auto-import, drag each
`SignalRGB_Glow_ScreenN.zip` onto Lively first.

**Wallpaper Engine:** either subscribe to / use the per-screen items
(*SignalRGB Glow - Screen 1 / 2*) and assign each to its monitor, or
use the **single combined item** (recommended): assign the same
wallpaper to every monitor and set a different *Screen index* per
assignment in WE's properties panel. Both routes connect to the
matching `?screen=N` on the bridge.

**Important:** the *number* in the tile / property corresponds to
which SignalRGB device the wallpaper subscribes to, not which
physical monitor it has to go on. The two are independent — you
decide the mapping by which host-monitor you activate it on.

### Step 4 — verify

Each wallpaper should now glow with a portion of your SignalRGB effect.
Switch SignalRGB effects to make sure the colours follow.

If a wallpaper stays black:

- Toggle *Show debug overlay* in the Configurator → that screen's
  tab → *Background* section — if the overlay on the wallpaper says
  `connecting` or `disconnected`, the bridge isn't running or its WS
  handshake is failing. See [troubleshooting.md](troubleshooting.md).
- Make sure the matching SignalRGB device is placed on the canvas at
  a non-empty area. A device with no canvas placement gets all-black
  pixels.

## Walkthrough: 3 monitors

Same as above but with `Number of screens = 3` and three zips. Canvas
layout suggestions:

- **3 in a row:** divide the canvas into vertical thirds, one device
  per third.
- **2+1 (e.g. two main + a vertical side monitor):** put Screen 1
  and Screen 2 side-by-side covering the bulk of the canvas, place
  Screen 3 as a small region wherever makes sense for the side monitor.

## Walkthrough: 4 monitors

Same flow with `Number of screens = 4` and four zips / four assignments
of the single WE bundle. Canvas layout suggestions:

- **4 in a row:** divide the canvas into quarters, one device per
  quarter. Pairs nicely with a 4× super-wide setup or a 1+3 row.
- **2 × 2 grid:** quad-monitor stacks (two on top of two). Place
  Screens 1/2 along the top of the canvas, Screens 3/4 along the
  bottom. Each device samples a quadrant of the effect.
- **3+1 (main triple + side):** Screens 1/2/3 cover the main
  triple-monitor block; Screen 4 lives in a small dedicated region
  for the side / portrait / control monitor.
- **Independent per-monitor sampling:** put all four devices on top
  of each other covering the full canvas — every monitor sees the
  whole effect, mirrored. Simplest layout if you don't care about
  spatial mapping.

Heads up on UDP throughput: at 128 × 128 grid × 4 screens × ~30 fps,
each frame is ~49 KB after chunking. That's still <2 MB/s on
localhost (no real load), but the SignalRGB plugin sandbox is on a
shared event loop — drop to 64 × 64 or 96 × 96 grid if you ever see
the plugin's tick stutter.

## Per-screen background images

Each screen tab in the Configurator is independent. You can:

- Use a different background PNG per monitor (e.g. each with cut-outs
  matching that monitor's "theme")
- Use the same PNG but different layouts / glow strengths
- Mix: one monitor's wallpaper shows pixel grid, another shows pills

## Reducing screen count later

If you set count = 4 and want to go back to 2 (or 3):

1. Configurator → top-right *Screens:* picker → pick the new value.
   The bridge persists it and pushes to every open Configurator tab.
2. The now-unused Screen N device(s) disappear from SignalRGB. Their
   canvas placement is **lost** — Configurator settings for the
   higher-indexed screens stay in `config.json`, so bumping the count
   back up restores them.
3. The wallpaper(s) for the dropped screen(s) stop receiving frames
   and show a blank glow layer. Deactivate them in Lively / Wallpaper
   Engine or they'll keep retrying the WS connection.
