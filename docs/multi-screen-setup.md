# Multi-Screen Setup

Driving glow on 2 or 3 monitors independently. Each monitor gets its
own SignalRGB device, its own canvas placement, and its own background
image + layout in the tray.

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

1. **SignalRGB plugin** must announce N devices (controlled via tray
   "Number of screens")
2. **SignalRGB canvas** must have those devices placed where you want
   colours sampled
3. **Lively** must show the matching wallpaper zip on each physical
   monitor

## Walkthrough: 2 monitors

Goal: monitor 1 shows the left half of your SignalRGB effect, monitor 2
shows the right half.

### Step 1 — set screen count to 2

Tray icon → Settings… → "Number of screens" = **2** → Save.

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

### Step 3 — import + activate the Lively wallpapers

Drag `SignalRGB_Glow_Screen1.zip` and `SignalRGB_Glow_Screen2.zip`
into Lively.

In Lively, each wallpaper tile has a screen selector when you right-click
→ "Set as wallpaper". For each tile, pick the matching physical monitor:

- **SignalRGB Glow - Screen 1** → Monitor 1 (your main display, usually)
- **SignalRGB Glow - Screen 2** → Monitor 2

**Important:** the *number* in the tile name corresponds to which
SignalRGB device it subscribes to, not which physical monitor it has to
go on. The two are independent — you decide the mapping by which Lively
monitor you activate it on. So if your "Monitor 1" in Windows is the
right-side display, just activate "Screen 1" tile on that monitor.

### Step 4 — verify

Each wallpaper should now glow with a portion of your SignalRGB effect.
Switch SignalRGB effects to make sure the colours follow.

If a wallpaper stays black:
- Toggle "Show debug overlay" in the tray Settings for that screen —
  if it says `connecting` or `disconnected`, the bridge isn't running
  or its WS handshake is failing. See [troubleshooting.md](troubleshooting.md).
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

## Per-screen background images

Each screen tab in the tray Settings is independent. You can:

- Use a different background PNG per monitor (e.g. each with cut-outs
  matching that monitor's "theme")
- Use the same PNG but different layouts / glow strengths
- Mix: one monitor's wallpaper shows pixel grid, another shows pills

## Reducing screen count later

If you set count = 3 and want to go back to 2:

1. Tray Settings → set "Number of screens" = 2 → Save.
2. The Screen 3 device disappears from SignalRGB. Its canvas placement
   is **lost**.
3. The Lively wallpaper for Screen 3 stops receiving frames and shows a
   blank glow layer. Deactivate it in Lively or it'll keep retrying.

The Screen 3 tab settings stay in `config.json` — if you bump the count
back to 3 later, the old settings come back.
