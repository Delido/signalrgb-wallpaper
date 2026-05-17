# Changelog

All notable changes to **SignalRGB Desktop Wallpaper** are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-05-17

First public release.

### Added
- Multi-screen support (1–3 monitors). The SignalRGB plugin announces one
  virtual device per screen; each pulls colours from its own canvas region.
- System tray icon (`SignalRGBBridge.exe`) with a per-screen settings dialog
  (background image picker, layout, glow strength, dim, blur, bar sliders,
  debug overlay toggle). Settings are pushed live to running wallpapers
  over WebSocket — no Lively reload required.
- Bridge-owned screen count: tray combo "Number of screens" controls how
  many devices SignalRGB exposes. The plugin polls the bridge's
  `GET /config` endpoint and removes excess controllers on the fly.
- Pre-baked Lively wallpaper bundles, one per monitor index: each
  hardcodes a screen-index meta tag so it subscribes to the correct
  per-screen UDP stream.
- HTTP image proxy at `/image?path=…` on port 17320 so the wallpaper page
  can load images from absolute filesystem paths despite Lively's CEF
  file:// sandbox.
- Standalone `SignalRGBBridge.exe` (PyInstaller `--onefile --noconsole`,
  ~19 MB, bundles pystray + Pillow + tkinter).

### Wire format
- UDP datagram layout: `[S][R][screen_index u8][width u16 BE][height u16 BE][rgb...]`
- WebSocket subscription: `ws://127.0.0.1:17320/?screen=N`

### Known limitations
- Lively's own "Customise wallpaper" panel is intentionally disabled for
  these wallpapers (no `LivelyProperties.json` shipped). All settings live
  in the bridge's tray dialog. See
  [docs/architecture.md](docs/architecture.md#why-not-lively-properties)
  for the reasoning.
- Lively non-MSIX (GitHub installer) is supported. Lively Microsoft Store
  (MSIX) version cannot load `.exe`-type wallpapers — irrelevant for this
  project (we use Type 1 / Web wallpapers) but worth flagging.
