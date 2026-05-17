# Tray Settings Reference

Every knob in the tray's Settings dialog, what it does, and when to
touch it.

## Opening the dialog

Right-click the tray icon (RGB monitor in the system tray) → **Settings…**.
A window with one global section at top + three tabs (Screen 1 / 2 / 3)
below opens. Click **Save** at the bottom to write changes to disk and
push them live to the wallpapers; **Cancel** discards.

## Global section: "SignalRGB device count"

### Number of screens — `1` / `2` / `3` (default: `1`)

Controls how many "Desktop Wallpaper - Screen N" devices the SignalRGB
plugin announces. The plugin polls the bridge's `/config` endpoint every
~2 seconds and adjusts: increasing adds devices, decreasing removes the
high-index ones.

> **Caveat:** when you reduce the count, devices removed from SignalRGB
> lose their canvas placement. If you had effects placed on Screen 3 and
> drop the count to 2, you'll need to re-place Screen 3 if you bump back
> to 3 later.

## Per-screen tab (Screen 1 / 2 / 3)

Each screen's settings are independent. The tray dialog always shows all
3 tabs even if you only have `Number of screens = 1` — the extra tabs'
settings are still saved (harmless, they apply when/if you enable that
screen).

### Background image

Browse and pick an image file. Used as the front layer; the glow shines
behind it. For the cut-out effect, use a PNG with **transparent regions**
where you want the SignalRGB colours to leak through.

Supports `.png .jpg .jpeg .gif .webp .svg .bmp`. Files at any absolute
path are served via the bridge's local HTTP proxy (port 17320), which
sidesteps Lively's CEF file:// sandbox restrictions.

### Image fit — `cover` / `contain` / `fill`

How the background image scales to fit the screen.

- **cover** — fill the screen; crop if needed to preserve aspect ratio
- **contain** — fit the screen; letterbox if needed
- **fill** — stretch to fit, ignoring aspect ratio

### Image dim — `0%` … `100%` (default: `0%`)

Darkens the entire composition. `0` = original colours, `100` = pitch
black (everything invisible). Useful if your wallpaper is too bright
and washes out the glow.

### Glow layout

Determines how the SignalRGB grid is rendered as glow:

- **Pixel Grid (2D)** — Uses the full N×N grid from SignalRGB as a 2D
  glow layer behind the image. Default. Best for detailed effects.
- **Vertical Stripes** — One column per grid column, full-screen height.
  Only uses the first row of the grid.
- **Horizontal Stripes** — One row per grid column, full-screen width.
  Only uses the first row of the grid.
- **Centered Pills** — Row of vertical "pill" bars centred on screen.
  Demo / showcase look.
- **Hidden (image only)** — No glow at all. Just the background image.

### Enable glow — checkbox (default: on)

Master toggle. Off = glow layer is hidden even if a layout is selected.

### Glow strength — `0%` … `200%` (default: `100%`)

Multiplier for blur radius and pill bloom. `0` = no blur (sharp pixels
in grid mode, hard pills in pill mode). `200` = very intense bloom.

### Grid blur — `0` … `200` px (default: `30`)

How much neighbouring pixel-grid cells bleed into each other. `0` =
sharp pixels, `200` = creamy gradient. **Pixel Grid layout only.**

### Stripes blur — `0` … `200` px (default: `60`)

Same idea, for the Vertical/Horizontal Stripes layouts. Higher = stripes
bleed together; lower = hard column/row boundaries.

### Bar height — `10%` … `100%` (default: `38%`)

**Pills layout only.** How tall the centered pills are, as a percentage
of screen height.

### Bar width — `1‰` … `50‰` (default: `14‰`)

**Pills layout only.** Width of each pill, in **per mille** of viewport
width. `14` = 1.4% — slim pills. Crank up for chunkier ones.

### Show debug overlay — checkbox (default: off)

Toggles the tiny status text in the top-left of each wallpaper:
`screen N live WxH @ fps`. Useful when first setting up or diagnosing
connection issues — leave off in regular use.

## What the dialog does on Save

1. Validates and clamps each value
2. Writes `%LOCALAPPDATA%\SignalRGBWallpaper\config.json`
3. Pushes the updated settings to every connected wallpaper page for the
   relevant screen as a WebSocket JSON text frame
4. The page applies them live — no Lively reload, no flicker

If the bridge can't write `config.json` (e.g. permission denied), the
changes apply in-memory (live push works) but won't persist across
bridge restarts.

## Tray menu options

- **Settings…** — opens the dialog described above
- **Reload config** — re-reads `config.json` from disk and pushes
  everything to all wallpapers. Use this if you edited the file by hand.
- **Quit** — hard-kills the bridge process. Wallpapers will see WS
  disconnect and start reconnecting; they'll stay blank until you
  restart the bridge.
