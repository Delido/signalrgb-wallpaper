"""
SignalRGB Desktop Wallpaper — bridge + tray + per-screen settings.

Single-process daemon with three concurrent jobs:

  1. asyncio loop (daemon thread)
        - UDP listener  :17320  (one datagram per frame from the plugin)
        - WebSocket fan-out :17320/?screen=N  (one route per monitor)
        - HTTP image proxy :17320/image?path=…  (CEF file:// workaround)
     Each datagram is tagged with a screen-index byte; matching WS clients
     get the raw datagram as a binary frame, others get nothing.
     On WS upgrade we also send the current per-screen settings as a JSON
     text frame so the page can apply background / layout / glow before
     the first paint.

  2. pystray tray icon (main thread, blocks on Win32 message pump)
        - Right-click menu: "Settings…", "Reload Config", "Quit"
        - "Settings…" pops a tkinter dialog with one tab per screen.
          Saving the dialog writes config.json AND pushes the new
          settings to all WS clients for that screen (live apply,
          no wallpaper reload).

  3. tkinter settings dialog (spawned per request, own thread)
        - Per-screen tab: background image picker, layout dropdown,
          glow / dim / blur sliders.

Config lives at %LOCALAPPDATA%\\SignalRGBWallpaper\\config.json.

Wire format (UDP, one frame per datagram):
  bytes 0..1   magic "SR"  (0x53 0x52)
  byte  2      screen index (u8)
  bytes 3..4   width  (u16 big-endian)
  bytes 5..6   height (u16 big-endian)
  bytes 7..    width*height RGB triplets, row-major
"""

from __future__ import annotations

import asyncio
import base64
import ctypes
from ctypes import wintypes
import hashlib
import copy
import json
import locale
import mimetypes
import os
import random
import re
import struct
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, ttk

import pystray
from PIL import Image, ImageDraw, ImageTk

# psutil is optional at import time so a dev `python bridge.py` on a box
# without it still boots. When missing, the SysStats broadcaster simply
# stays disabled and the CPU / RAM / Net widgets render "n/a".
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    psutil = None
    _HAS_PSUTIL = False


def _resource_path(rel: str) -> Path:
    """Resolve a path that works both in dev runs and PyInstaller --onefile
    bundles. PyInstaller extracts bundled --add-data files into a temp dir
    pointed to by sys._MEIPASS; in dev the file sits next to bridge.py."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / rel
    return Path(__file__).parent / rel


# ============================================================================
# Fullscreen detection (Win32)
# ============================================================================

_user32 = ctypes.windll.user32 if sys.platform == "win32" else None


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize",    wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork",    wintypes.RECT),
        ("dwFlags",   wintypes.DWORD),
    ]


def _is_fullscreen_active() -> bool:
    """True if the foreground window covers its entire monitor and isn't
    the shell/desktop. Catches both exclusive fullscreen and borderless-
    fullscreen games / video players. Cheap to call (a few syscalls)."""
    if not _user32:
        return False
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return False
        shell = _user32.GetShellWindow()
        if hwnd == shell:
            return False
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        hmon = _user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        if not hmon:
            return False
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        if not _user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return False
        return (rect.left   == mi.rcMonitor.left  and
                rect.top    == mi.rcMonitor.top   and
                rect.right  == mi.rcMonitor.right and
                rect.bottom == mi.rcMonitor.bottom)
    except Exception:
        return False


class FullscreenWatcher:
    """Polls _is_fullscreen_active() every second and fires a callback
    when the boolean flips. Runs on its own daemon thread; respects an
    `is_enabled` callable so the user's "pause on fullscreen" toggle in
    the tray can disable the feature without restarting the bridge."""

    def __init__(self, on_state_change, is_enabled):
        self._on = on_state_change   # callable(active: bool)
        self._enabled = is_enabled   # callable() -> bool
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="fullscreen-watcher")
        self._last = False

    def start(self):
        if self._thread.is_alive():
            return
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def is_paused(self) -> bool:
        return self._last

    def _run(self):
        while not self._stop.wait(1.0):
            try:
                if not self._enabled():
                    if self._last:
                        self._last = False
                        self._on(False)
                    continue
                current = _is_fullscreen_active()
                if current != self._last:
                    self._last = current
                    self._on(current)
            except Exception as e:
                print(f"[fullscreen] watch error: {e}")

# ============================================================================
# Update checker
# ============================================================================

UPDATE_API_URL          = "https://api.github.com/repos/Delido/signalrgb-wallpaper/releases"
UPDATE_RELEASES_HTML    = "https://github.com/Delido/signalrgb-wallpaper/releases"
UPDATE_CHECK_INTERVAL_S = 24 * 3600    # daily background poll
UPDATE_STARTUP_DELAY_S  = 12           # let the bridge settle before the first call


def _parse_version(s: str) -> tuple:
    """Parse 'v0.5.1', '0.5.1' or '0.5.1-beta' into a sortable tuple.

    Stable releases sort *after* any prerelease of the same MAJOR.MINOR.PATCH,
    which matches semver semantics ('1.0.0-beta' < '1.0.0'). Returns
    (major, minor, patch, channel, pre_label) where channel is 1 for stable
    and 0 for prerelease. Garbage strings sort to (0,0,0,…) so they never
    trigger a false-positive 'newer than current' result for a real version.
    """
    s = (s or "").strip().lstrip("vV")
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-+](.+))?$", s)
    if not m:
        return (0, 0, 0, 0, "")
    major, minor, patch, pre = m.groups()
    return (int(major), int(minor), int(patch), 0 if pre else 1, pre or "")


class UpdateChecker:
    """Polls the GitHub releases API once on startup (after a short delay)
    and once a day thereafter. Honours config flags:
      - updateCheckEnabled: master switch
      - allowBetas:         include prerelease tags in the comparison
    On detection of a newer version, calls on_update_available(tag, html_url).
    The tray menu queries available()/latest_url() between polls; check_now()
    triggers an immediate retry from the 'Check for updates now' menu entry."""

    def __init__(self, config: dict, config_lock: threading.Lock, on_update_available, on_check_done):
        self.config = config
        self.config_lock = config_lock
        self.on_update_available = on_update_available  # callable(tag, html_url)
        self.on_check_done = on_check_done              # callable(found: bool, error: str|None)
        self._stop = threading.Event()
        self._available_tag: str | None = None
        self._available_url: str | None = None
        # Direct download URL for the installer asset on the newer
        # release — lets the tray "Download + install" flow grab the
        # exe without re-querying the GitHub API.
        self._available_asset_url: str | None = None
        self._available_asset_size: int = 0
        self._last_checked_ts: float = 0.0
        self._last_error: str | None = None

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="update-checker").start()

    def stop(self):
        self._stop.set()

    # ── queried by the tray menu ────────────────────────────────────────
    def available(self) -> tuple[str, str] | None:
        if self._available_tag:
            return (self._available_tag, self._available_url or UPDATE_RELEASES_HTML)
        return None

    def available_asset(self) -> tuple[str, int] | None:
        """Direct URL + content-length for the newer release's installer
        asset, or None when no update is pending or the release didn't
        include an installer attachment."""
        if self._available_tag and self._available_asset_url:
            return (self._available_asset_url, self._available_asset_size)
        return None

    def last_checked(self) -> float:
        return self._last_checked_ts

    def last_error(self) -> str | None:
        return self._last_error

    def check_now(self):
        threading.Thread(target=self._safe_check, daemon=True, name="update-check-now").start()

    def download_and_install(self, on_progress=None, on_done=None) -> None:
        """Download the pending update's installer to %TEMP%, launch it
        silently with /VERYSILENT /SUPPRESSMSGBOXES, then exit the bridge
        so the installer can replace SignalRGBBridge.exe.

        on_progress(bytes_done, total_bytes) is called periodically.
        on_done(path | None, error | None) fires when the install spawn
        succeeds (path) or the flow aborts (error)."""
        threading.Thread(
            target=self._download_install_worker,
            args=(on_progress, on_done),
            daemon=True, name="update-install").start()

    def _download_install_worker(self, on_progress, on_done):
        asset = self.available_asset()
        if not asset:
            if on_done: on_done(None, "no installer asset on the latest release")
            return
        url, declared_size = asset
        try:
            tmp_dir  = Path(os.environ.get("TEMP", str(Path.home() / "AppData" / "Local" / "Temp")))
            tmp_dir.mkdir(parents=True, exist_ok=True)
            # Stamp the file with the version tag so a partial download
            # from a previous attempt doesn't masquerade as the new one.
            tag_clean = re.sub(r"[^A-Za-z0-9._-]", "", self._available_tag or "update")
            target = tmp_dir / f"SignalRGBWallpaperSetup-{tag_clean}.exe"
            if target.exists():
                try: target.unlink()
                except OSError: pass
            req = urllib.request.Request(
                url,
                headers={"User-Agent": f"SignalRGBWallpaper-Updater/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(target, "wb") as fp:
                total = int(resp.headers.get("Content-Length") or declared_size or 0)
                done = 0
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    fp.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        try: on_progress(done, total)
                        except Exception: pass
            print(f"[update] downloaded {done:,} bytes → {target}")
        except Exception as e:
            print(f"[update] download failed: {e}")
            if on_done: on_done(None, str(e))
            return
        # Spawn the installer detached, then exit so it can replace our
        # exe. /VERYSILENT runs without a UI; /SUPPRESSMSGBOXES kills
        # the "are you sure?" prompts. The bridge tray icon will
        # disappear; the new exe re-launches it on install completion
        # via the [Run] section the installer already has.
        try:
            import subprocess
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            subprocess.Popen(
                [str(target), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                close_fds=True,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
            print(f"[update] installer spawned; exiting bridge to release file locks")
        except Exception as e:
            print(f"[update] installer spawn failed: {e}")
            if on_done: on_done(None, str(e))
            return
        if on_done:
            try: on_done(str(target), None)
            except Exception: pass
        # Give the spawned installer a moment to grab its handles
        # before we kill the bridge process.
        time.sleep(1.5)
        # Hard-exit — graceful shutdown would let other threads block
        # the installer's overwrite of SignalRGBBridge.exe.
        os._exit(0)

    # ── internals ───────────────────────────────────────────────────────
    def _enabled(self) -> bool:
        with self.config_lock:
            return bool(self.config.get("updateCheckEnabled", True))

    def _allow_betas(self) -> bool:
        with self.config_lock:
            return bool(self.config.get("allowBetas", False))

    def _run(self):
        if self._stop.wait(UPDATE_STARTUP_DELAY_S):
            return
        while not self._stop.is_set():
            if self._enabled():
                self._safe_check()
            if self._stop.wait(UPDATE_CHECK_INTERVAL_S):
                return

    def _safe_check(self):
        try:
            self._check()
            self._last_error = None
            self.on_check_done(self._available_tag is not None, None)
        except Exception as e:
            self._last_error = str(e)
            print(f"[update] check failed: {e}")
            self.on_check_done(False, str(e))

    def _check(self):
        self._last_checked_ts = time.time()
        req = urllib.request.Request(UPDATE_API_URL, headers={
            "Accept":     "application/vnd.github+json",
            "User-Agent": f"SignalRGBWallpaper-Updater/{APP_VERSION}",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, list):
            raise RuntimeError("releases endpoint returned non-list payload")
        allow_betas = self._allow_betas()
        current = _parse_version(APP_VERSION)
        best: tuple = current
        best_tag = ""
        best_url = ""
        best_asset_url = ""
        best_asset_size = 0
        for rel in data:
            if not isinstance(rel, dict) or rel.get("draft"):
                continue
            if rel.get("prerelease") and not allow_betas:
                continue
            tag = rel.get("tag_name") or ""
            v = _parse_version(tag)
            if v > best:
                best = v
                best_tag = tag
                best_url = rel.get("html_url") or UPDATE_RELEASES_HTML
                # Find the installer asset on this release. Match by
                # the canonical filename prefix so we ignore zips,
                # source tarballs, and any future extra artefacts.
                assets = rel.get("assets") or []
                best_asset_url = ""
                best_asset_size = 0
                for a in assets:
                    if not isinstance(a, dict):
                        continue
                    name = (a.get("name") or "")
                    if (name.lower().startswith("signalrgbwallpapersetup")
                            and name.lower().endswith(".exe")):
                        best_asset_url  = a.get("browser_download_url") or ""
                        best_asset_size = int(a.get("size") or 0)
                        break
        if best > current:
            prev = self._available_tag
            self._available_tag        = best_tag
            self._available_url        = best_url
            self._available_asset_url  = best_asset_url or None
            self._available_asset_size = best_asset_size
            if prev != best_tag:    # only fire on first detection / new bump
                print(f"[update] newer release available: {best_tag} (current {APP_VERSION})")
                try: self.on_update_available(best_tag, best_url)
                except Exception as e: print(f"[update] notify failed: {e}")
        else:
            self._available_tag = None
            self._available_url = None
            self._available_asset_url = None
            self._available_asset_size = 0
            print(f"[update] no newer release; current {APP_VERSION} is up to date "
                  f"(allow_betas={allow_betas})")


# ============================================================================
# Constants
# ============================================================================

APP_NAME    = "SignalRGB Wallpaper Bridge"
APP_VERSION = "0.9.11-beta"
APP_AUTHOR  = "Sebastian Mendyka"
APP_GITHUB_USER = "Delido"
APP_REPO    = f"https://github.com/{APP_GITHUB_USER}/signalrgb-wallpaper"
APP_AUTHOR_URL = f"https://github.com/{APP_GITHUB_USER}"
APP_CREDITS_URL = f"{APP_REPO}/blob/main/docs/credits.md"
APP_DONATE_URL  = "https://paypal.me/SMendyka"

UDP_HOST = "127.0.0.1"
UDP_PORT = 17320
WS_HOST  = "127.0.0.1"
WS_PORT  = 17320

# Max payload size accepted on POST /screen/<N>/background. Generous (50 MB)
# but bounded — the builder caps output well below this in practice.
MAX_BACKGROUND_UPLOAD_BYTES = 50 * 1024 * 1024

WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_SCREEN_INDEX = 7  # generous upper bound; plugin caps at 3 (4 screens)
N_SCREENS = 4

CONFIG_VERSION = 1
DEFAULT_SCREEN_SETTINGS = {
    "bgImage":      "",
    "bgImageUrl":   "",
    "bgFit":        "cover",
    "bgDim":        0,
    "barLayout":    "lay-grid",
    "showBars":     True,
    "glowStrength": 100,
    "gridBlur":     30,
    "stripesBlur":  60,
    "barHeight":    38,
    "barWidth":     14,
    "showStatus":   False,
    # Placeable HTML widgets (clock / calendar / weather, more coming).
    # Each entry: {"id":"w_<int>", "type":"clock|calendar|weather",
    #              "x":int, "y":int, "w":int, "h":int,
    #              "options": {…}}. Positions are CSS pixels relative to
    #              the wallpaper page's viewport.
    "widgets":         [],
    # When True the wallpaper renders widgets read-only. When False the
    # wallpaper attaches drag/resize handles (via interact.js) and pushes
    # position updates back over the WS as widget-update messages.
    "widgetsLocked":   True,
    # Full-canvas ambient effect (Phase 2). One of:
    #   "off" | "snow" | "rain" | "sparks" | "aurora"
    "ambientEffect":   "off",
    # When True the ambient effect samples the live glow colour and tints
    # particles accordingly (snow → wallpaper-coloured, etc.). Off by default
    # so snow stays white / rain stays bluish.
    "ambientTint":     False,
    # 1..100 — relative particle count / saturation knob.
    "ambientDensity":  60,
    # Cursor / click eye-candy (Phase 4). One of:
    #   "off" | "trail" | "glow" | "ripple" | "all"
    # Position arrives via Lively's livelyCurrentCursorPos callback so the
    # trail works even with click-through enabled; ripples need real clicks
    # (Lively interaction must be on).
    "pixelfx":         "off",
    # Parallax 3D — when > 0 the background image translates a fraction
    # of the cursor offset (smooth lerp), creating a fake-depth effect.
    # Value is the maximum displacement in CSS pixels at the cursor's
    # most extreme corner. 0 = off (default). 30 is gentle, 80 is strong.
    "parallax3d":      0,
    # Whole-screen audio-reactive glow layer. Driven by the same FFT data
    # the audio-spectrum widget already drains (Lively's
    # livelyAudioListener / WE's wallpaperRegisterAudioListener).
    # Modes: "off" | "pulse" | "spectrum" | "wave".
    "audioGlow":            "off",
    "audioGlowIntensity":   60,    # 0..100
    "audioGlowTint":        False, # tint with the live glow-feed average
    # Last known viewport reported by the wallpaper page itself (in CSS
    # pixels). The bridge can't ask Windows directly because each page
    # lives on whichever monitor Lively / WE assigns it; the page knows.
    # Used by the configurator's layout-preview to scale to the real
    # screen instead of guessing FullHD. 0 = not yet reported.
    "viewportW":       0,
    "viewportH":       0,
    # Per-screen preset slots. Each slot is either None (empty) or a
    # snapshot dict of every settable screen key (see PRESET_SNAPSHOT_KEYS
    # below). The Configurator surfaces N slot buttons; Save captures the
    # current state, Apply writes the snapshot back into the screen's
    # settings, Clear sets the slot to None.
    "presets":         [None, None, None, None],
    # Mirror mode: when set to another screen index, this screen's settings
    # are kept in lockstep with that screen's. The bridge:
    #   - copies all mirrorable keys from the source on activation
    #   - replicates every per-screen mutation of the source to the mirror
    #   - rejects direct mutations of the mirror (read-only)
    # `None` means "not mirroring". Self-mirror and chains (A→B→C) are
    # rejected at the WS / HTTP entry point.
    "mirrorOf":        None,
    # Auto-cycle through library entries on a schedule. When enabled,
    # CycleScheduler picks the next pool entry every `intervalMin` minutes
    # and applies it as the screen's background via _update_background.
    # `pool` is one of "all" | "pinned"; `order` is "sequential" | "random".
    # `lastApplyMs` / `nextIdx` are managed by the scheduler — exposed in
    # the config so they survive a restart.
    "cycle":           {
        "enabled":     False,
        "intervalMin": 10,
        "pool":        "all",
        "order":       "sequential",
        "lastApplyMs": 0,
        "nextIdx":     0,
    },
}

# Keys that get replicated to mirror screens. Per-screen physical
# attributes (viewport, mirrorOf itself) stay independent, otherwise
# the mirror would lose its identity. Presets aren't mirrored because
# they're user-curated per-screen scratch space. `cycle` isn't mirrored
# — only the source's cycle runs; the mirror inherits the resulting
# bgImage change through the existing replication path.
_NON_MIRRORED_KEYS = frozenset({
    "viewportW", "viewportH", "mirrorOf", "presets", "cycle",
})

# Keys that get rolled up into a preset snapshot. Excludes anything the
# wallpaper page reports back (viewports), anything transient (locks), and
# the preset list itself (so a preset can't recursively contain its
# siblings).
PRESET_SNAPSHOT_KEYS = (
    "bgImage", "bgImageUrl", "bgFit", "bgDim",
    "barLayout", "showBars", "glowStrength",
    "gridBlur", "stripesBlur", "barHeight", "barWidth",
    "showStatus",
    "widgets",
    "ambientEffect", "ambientTint", "ambientDensity",
    "pixelfx", "parallax3d",
    "audioGlow", "audioGlowIntensity", "audioGlowTint",
)
PRESET_SLOTS = 4

# Server-side schemas for widget option defaults — keep in sync with the
# wallpaper-page renderers. Tray "Add widget" uses these to seed a fresh
# entry; client-side options editor (later) writes back through the same
# WS protocol.
# Each entry: position + size at spawn, the type-specific options blob, and
# a tray-menu label. The wallpaper page mirrors the keys in its WIDGET_REGISTRY
# so the in-page picker and the tray "Add…" submenu both stay in sync.
WIDGET_DEFAULTS = {
    "clock": {
        "label":   "Clock",
        "x": 60, "y": 60, "w": 220, "h": 220,
        "options": {"style": "analog", "format24h": True, "tintFromGlow": False},
    },
    "calendar": {
        "label":   "Calendar",
        "x": 60, "y": 320, "w": 260, "h": 240,
        "options": {"tintFromGlow": False, "weekStart": 1},   # 0=Sun, 1=Mon
    },
    "weather": {
        "label":   "Weather",
        "x": 60, "y": 600, "w": 240, "h": 140,
        "options": {"lat": 52.52, "lon": 13.405, "label": "Berlin",
                    "units": "metric", "tintFromGlow": False},
    },
    "sticky-note": {
        "label":   "Sticky note",
        "x": 340, "y": 60, "w": 220, "h": 180,
        "options": {"text": "Double-click in edit mode to write a note.",
                    "color": "yellow", "tintFromGlow": False},
    },
    "countdown": {
        "label":   "Countdown",
        "x": 340, "y": 280, "w": 240, "h": 140,
        # Target gets seeded by the wallpaper page on first render (we
        # can't sensibly hardcode a date in this Python file). Empty
        # string here means "use today + 30 days as default".
        "options": {"target": "", "label": "Event",
                    "units": "smart", "tintFromGlow": False},
    },
    "picture-frame": {
        "label":   "Picture frame",
        "x": 340, "y": 460, "w": 260, "h": 200,
        "options": {"url": "", "fit": "cover", "rounded": True,
                    "tintFromGlow": False},
    },
    "quote": {
        "label":   "Quote of the day",
        "x": 600, "y": 60,  "w": 320, "h": 180,
        "options": {"source": "quotable", "tintFromGlow": False},
    },
    "cpu-meter": {
        "label":   "CPU meter",
        "x": 600, "y": 260, "w": 200, "h": 140,
        "options": {"tintFromGlow": False},
    },
    "ram-meter": {
        "label":   "RAM meter",
        "x": 600, "y": 420, "w": 200, "h": 140,
        "options": {"tintFromGlow": False},
    },
    "audio-spectrum": {
        "label":   "Audio spectrum",
        "x": 820, "y": 440, "w": 280, "h": 120,
        "options": {"tintFromGlow": False},
    },
    # Generic LibreHardwareMonitor-driven sensor display. Empty
    # sensorPath = blank widget on the wallpaper; user opens the
    # Configurator's options modal to pick a sensor from the dropdown
    # populated by /hwmon/sensors. Decimals defaults to 1 (good for
    # temps in °C and most voltages); explicit label override is empty
    # so the widget falls back to the sensor's leaf-segment as label.
    "hardware-sensor": {
        "label":   "Hardware sensor",
        "x": 600, "y": 580, "w": 220, "h": 140,
        "options": {"sensorPath": "", "label": "", "decimals": 1,
                    "tintFromGlow": False},
    },
    # Now-playing widget — reads the live media session published by
    # NowPlayingPoller (Windows SMTC). Shows title + artist + a thin
    # progress bar; auto-hides itself when no media session is active.
    "now-playing": {
        "label":   "Now playing",
        "x": 1100, "y": 580, "w": 320, "h": 96,
        "options": {"showProgress": True, "showArtist": True,
                    "tintFromGlow": False},
    },
}
WIDGET_TYPES = list(WIDGET_DEFAULTS.keys())

# Choices that must match the wallpaper HTML / CSS class names.
BG_FIT_CHOICES   = ["cover", "contain", "fill"]
LAYOUT_CHOICES   = [
    ("lay-grid",     "Pixel Grid (2D)"),
    ("lay-vstripes", "Vertical Stripes"),
    ("lay-hstripes", "Horizontal Stripes"),
    ("lay-pills",    "Centered Pills"),
    ("lay-off",      "Hidden (image only)"),
]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/webp",   ".webp")


# ============================================================================
# Config: load / save / defaults
# ============================================================================

def config_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    folder = Path(base) / "SignalRGBWallpaper"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "config.json"


def _candidate_documents_dirs() -> list[Path]:
    """Every plausible location for the user's "Documents" folder, in
    preference order. Windows redirects Documents to OneDrive on a lot
    of installs — `Path.home() / "Documents"` will exist but be empty
    when that happens, while Inno Setup's `{userdocs}` token routes
    through `SHGetFolderPath(CSIDL_PERSONAL)` and writes to the actual
    OneDrive-backed path. We mirror that resolution here so the
    System-status dialog finds the plugin file in the same place the
    installer dropped it.

    Order:
      1. HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\
         Shell Folders\\Personal — authoritative, matches `{userdocs}`
      2. Detected `~/OneDrive*/Documents` and `~/OneDrive*/Dokumente`
         siblings for users where the registry value lags a sync
      3. Plain `~/Documents` / `~/Dokumente` as the legacy fallback
    """
    seen: set[str] = set()
    out: list[Path] = []
    def add(p: Path | None):
        if p is None:
            return
        try:
            resolved = p.resolve()
        except Exception:
            resolved = p
        key = str(resolved).lower()
        if key in seen:
            return
        seen.add(key)
        out.append(resolved)

    # 1) Registry "Personal" value — the one Windows itself uses.
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        ) as k:
            value, _ = winreg.QueryValueEx(k, "Personal")
            add(Path(os.path.expandvars(value)))
    except Exception:
        pass
    # User Shell Folders carries the unexpanded version (with env vars
    # like %USERPROFILE%) which can be more accurate when the cache
    # in Shell Folders is stale.
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as k:
            value, _ = winreg.QueryValueEx(k, "Personal")
            add(Path(os.path.expandvars(value)))
    except Exception:
        pass

    # 2) Any OneDrive root under the home folder (personal + corp).
    try:
        home = Path.home()
        for child in home.iterdir():
            name = child.name
            if name.lower().startswith("onedrive") and child.is_dir():
                for doc_name in ("Documents", "Dokumente"):
                    cand = child / doc_name
                    if cand.is_dir():
                        add(cand)
    except Exception:
        pass

    # 3) Plain home/Documents and the German variant.
    for doc_name in ("Documents", "Dokumente"):
        add(Path.home() / doc_name)

    return out


def screens_dir() -> Path:
    """Where builder-uploaded backgrounds get persisted, one file per
    screen with a unix-millis timestamp suffix so the browser can't cache
    a stale image after re-upload."""
    p = config_path().parent / "screens"
    p.mkdir(parents=True, exist_ok=True)
    return p


_LIBRARY_SAFE_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789-_"

def _library_slug(label: str, lib: Path) -> str:
    """Make a filesystem-safe slug from a user-provided label, avoiding
    collisions with existing files in `lib`. Trimmed to 60 chars."""
    s = "".join(c if c in _LIBRARY_SAFE_CHARS else "-" for c in (label or "").lower())
    while "--" in s: s = s.replace("--", "-")
    s = s.strip("-") or "untitled"
    s = s[:60]
    base = s
    i = 2
    while any((lib / (base + ext)).exists() for ext in (".png", ".jpg", ".webp")):
        base = f"{s}-{i}"
        i += 1
    return base


def _library_rebuild_catalogue(lib: Path) -> None:
    """Rescan the library folder and rewrite library.json with one entry
    per image. Files matching `<stem>.thumb.png` are paired as thumbs
    with their main image; everything else becomes a tile without an
    explicit thumb (the Configurator falls back to the main file).

    User-state fields (`pinned`, `order`, `addedAt`) are preserved from
    the previous catalogue if the file still exists — that way an
    upload/delete/rename doesn't wipe the user's pin and drag-reorder
    state. `addedAt` is initialised from file mtime for new entries so
    "sort by newest first" works out of the box for fresh uploads."""
    prev_by_file: dict[str, dict] = {}
    cat_path = lib / "library.json"
    if cat_path.exists():
        try:
            prev = json.loads(cat_path.read_text(encoding="utf-8"))
            for it in prev.get("items", []):
                if isinstance(it, dict) and "file" in it:
                    prev_by_file[it["file"]] = it
        except Exception:
            pass

    items = []
    files = sorted([p for p in lib.iterdir()
                    if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")])
    stems = {p.name for p in files}
    for fp in files:
        stem = fp.stem
        # Skip thumbnail siblings — they'll be linked from their parent.
        if stem.endswith(".thumb"):
            continue
        thumb = None
        for cand in (stem + ".thumb.png", stem + ".thumb.jpg", stem + ".thumb.webp"):
            if cand in stems:
                thumb = cand
                break
        prev_it = prev_by_file.get(fp.name) or {}
        try:
            added_at_default = int(fp.stat().st_mtime * 1000)
        except OSError:
            added_at_default = int(time.time() * 1000)
        entry = {
            "id":      stem,
            "label":   stem.replace("-", " ").replace("_", " ").title(),
            "file":    fp.name,
            "thumb":   thumb or fp.name,
            "pinned":  bool(prev_it.get("pinned", False)),
            "order":   prev_it.get("order"),
            "addedAt": prev_it.get("addedAt", added_at_default),
        }
        if entry["order"] is None:
            del entry["order"]
        items.append(entry)

    cat_path.write_text(
        json.dumps({"version": 1, "items": items}, indent=2),
        encoding="utf-8",
    )


def _library_update_item(lib: Path, file: str, mutator) -> dict | None:
    """Apply mutator(entry_dict) to the library.json item matching
    `file`, persist, and return the updated entry. Returns None if no
    such entry exists. Used by the pin/reorder endpoints — they touch
    user-state fields but not the directory contents, so a full
    catalogue rebuild isn't needed."""
    cat_path = lib / "library.json"
    if not cat_path.exists():
        return None
    try:
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    items = cat.get("items", [])
    target = None
    for it in items:
        if isinstance(it, dict) and it.get("file") == file:
            target = it
            break
    if target is None:
        return None
    mutator(target)
    cat["items"] = items
    cat_path.write_text(json.dumps(cat, indent=2), encoding="utf-8")
    return target


def _library_apply_order(lib: Path, order: list[str]) -> int:
    """Assign sequential `order` indices to entries whose `file` field
    matches the given list. Entries not in the list keep their
    existing order (if any) but are pushed past the end of the new
    list. Returns the number of items that received an order."""
    cat_path = lib / "library.json"
    if not cat_path.exists():
        return 0
    try:
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    items = cat.get("items", [])
    by_file = {it.get("file"): it for it in items if isinstance(it, dict)}
    n = 0
    for idx, file in enumerate(order):
        it = by_file.get(file)
        if it is not None:
            it["order"] = idx
            n += 1
    # Entries not in the new order: push past the end so they sort
    # last but stay reachable. Stable across multiple reorder rounds.
    tail = len(order)
    for it in items:
        if isinstance(it, dict) and it.get("file") not in order:
            it["order"] = tail
            tail += 1
    cat["items"] = items
    cat_path.write_text(json.dumps(cat, indent=2), encoding="utf-8")
    return n


def library_dir() -> Path:
    """Curated starter-wallpaper library. The installer drops PNGs +
    library.json here; the Configurator's `Library` section browses
    them. Users can also drop their own PNGs in here by hand — the
    bridge serves anything that's whitelisted by name, and missing
    library.json just yields an empty browser. When running from
    Python source (no installer), prefer the build-time output under
    `wallpaper_bridge/library/` so dev iterations don't require a
    full install cycle."""
    user_dir = config_path().parent / "library"
    if user_dir.exists() and any(user_dir.iterdir()):
        return user_dir
    # Dev fallback: the build-time library next to the bridge source.
    dev_dir = Path(__file__).resolve().parent / "library"
    if dev_dir.exists():
        return dev_dir
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def default_config() -> dict:
    return {
        "version": CONFIG_VERSION,
        "screenCount": 1,         # plugin polls /config and announces this many controllers
        "fullscreenPause": True,  # auto-pause glow when a fullscreen app is active
        "updateCheckEnabled": True,
        "allowBetas":         False,   # include GitHub prerelease tags in update checks
        "language":           "auto",  # "auto" | "en" | "de" — UI language
        # Global Ctrl+Shift+1..4 → apply preset slot 1..4 on every active
        # screen. Disabled by default so we don't grab shortcuts the user
        # might already have wired up; tray menu flips it on.
        "presetHotkeysEnabled": False,
        # Per-app / per-game profile rules. ProfileWatcher polls
        # GetForegroundWindow every 1 s; matching rules swap the
        # target screen's preset and revert when the foreground
        # changes away. List of dicts (see ProfileWatcher).
        "profiles": [],
        "screens": {str(n): dict(DEFAULT_SCREEN_SETTINGS) for n in range(N_SCREENS)},
    }


# ============================================================================
# Localisation (DE / EN)
# ============================================================================
#
# Single-file string table. `tr(key)` returns the localised string for the
# active language; format parameters get spliced in via str.format. Falls
# back to English then to the key itself, so an untranslated string never
# crashes — it just shows up as the dotted-key, which makes missing entries
# obvious during dev.
#
# Coverage: tray menu, About dialog, the Configurator's main labels, and
# (since v0.7.4-beta) the Builder window — the Builder has its own
# in-page TRANSLATIONS map and fetches the active language from /config.
# ----------------------------------------------------------------------------

TRANSLATIONS = {
    # ── Tray menu ────────────────────────────────────────────────────
    "tray.configurator":        {"en": "Configurator…",           "de": "Konfigurator…"},
    "tray.builder":             {"en": "Build Wallpaper…",        "de": "Wallpaper bauen…"},
    "tray.help":                {"en": "Help…",                   "de": "Hilfe…"},
    "tray.status":              {"en": "System status…",          "de": "Systemstatus…"},
    # ── System Status dialog ────────────────────────────────────────
    "status.title":             {"en": "System status",
                                 "de": "Systemstatus"},
    "status.subtitle":          {"en": "Quick check of every signal that has to be green for the wallpaper to actually light up.",
                                 "de": "Kurzcheck aller Signale, die grün sein müssen, damit das Wallpaper leuchtet."},
    "status.plugin":            {"en": "SignalRGB plugin file installed",
                                 "de": "SignalRGB-Plugin-Datei installiert"},
    "status.signalrgb":         {"en": "SignalRGB.exe running",
                                 "de": "SignalRGB.exe läuft"},
    "status.bridge":            {"en": "Bridge reachable on {host}:{port}",
                                 "de": "Bridge erreichbar auf {host}:{port}"},
    "status.pages":             {"en": "Wallpaper pages connected: {n}",
                                 "de": "Verbundene Wallpaper-Seiten: {n}"},
    "status.lhm":               {"en": "LibreHardwareMonitor reachable ({n} sensors)",
                                 "de": "LibreHardwareMonitor erreichbar ({n} Sensoren)"},
    "status.btn.open_plugins":  {"en": "Open plugins folder",
                                 "de": "Plugin-Ordner öffnen"},
    "status.btn.get_signalrgb": {"en": "Download SignalRGB",
                                 "de": "SignalRGB herunterladen"},
    "status.btn.get_lhm":       {"en": "Download LHM",
                                 "de": "LHM herunterladen"},
    "status.btn.help":          {"en": "Open Help",
                                 "de": "Hilfe öffnen"},
    "status.btn.refresh":       {"en": "Refresh",
                                 "de": "Aktualisieren"},
    "tray.lock_all":            {"en": "🔓 Lock widgets (all screens)",
                                 "de": "🔓 Widgets sperren (alle Bildschirme)"},
    "tray.unlock_all":          {"en": "🔒 Unlock widgets (all screens)",
                                 "de": "🔒 Widgets entsperren (alle Bildschirme)"},
    "tray.advanced":            {"en": "Advanced",                "de": "Erweitert"},
    "tray.legacy_settings":     {"en": "Legacy Settings dialog…",
                                 "de": "Klassischer Settings-Dialog…"},
    "tray.quick_add_widget":    {"en": "Quick add widget",        "de": "Widget schnell hinzufügen"},
    "tray.quick_effects":       {"en": "Quick effects",           "de": "Effekte (Schnellzugriff)"},
    "tray.reload_config":       {"en": "Reload config",           "de": "Konfig neu laden"},
    "tray.preset_hotkeys":      {"en": "Preset hotkeys (Ctrl+Shift+1..4)",
                                 "de": "Preset-Hotkeys (Strg+Umschalt+1..4)"},
    "tray.updates":             {"en": "Updates",                 "de": "Updates"},
    "tray.about":               {"en": "About…",                  "de": "Über…"},
    "tray.quit":                {"en": "Quit",                    "de": "Beenden"},
    "tray.screen_n":            {"en": "Screen {n}",              "de": "Bildschirm {n}"},
    # ── Updates submenu ─────────────────────────────────────────────
    "updates.check_now":        {"en": "Check for updates now",   "de": "Jetzt nach Updates suchen"},
    "updates.enable":           {"en": "Enable update checks",    "de": "Update-Suche aktivieren"},
    "updates.allow_beta":       {"en": "Allow beta versions",     "de": "Beta-Versionen erlauben"},
    "updates.latest":           {"en": "Latest: {tag} — open release page",
                                 "de": "Verfügbar: {tag} — Release-Seite öffnen"},
    "updates.up_to_date":       {"en": "Up to date — last checked {ago}",
                                 "de": "Aktuell — zuletzt geprüft {ago}"},
    "updates.not_checked":      {"en": "Not yet checked",         "de": "Noch nicht geprüft"},
    "updates.last_failed":      {"en": "Last check failed: {err}",
                                 "de": "Letzte Prüfung fehlgeschlagen: {err}"},
    "updates.install_now":      {"en": "⬇  Download + install {tag}",
                                 "de": "⬇  {tag} herunterladen + installieren"},
    "updates.installing_title": {"en": "Installing {tag}",
                                 "de": "Installiere {tag}"},
    "updates.installing_start": {"en": "Starting download…",
                                 "de": "Download startet…"},
    "updates.installing_progress": {"en": "Downloading… {pct}%  ({done_mb} / {total_mb} MB)",
                                 "de": "Lade herunter… {pct}%  ({done_mb} / {total_mb} MB)"},
    "updates.installing_done":  {"en": "Installer launched — bridge will restart automatically.",
                                 "de": "Installer gestartet — Bridge wird automatisch neugestartet."},
    "updates.installing_failed": {"en": "Update failed: {msg}",
                                 "de": "Update fehlgeschlagen: {msg}"},
    "updates.installing_hint":  {"en": "The bridge will exit when the installer takes over. Don't close this window manually.",
                                 "de": "Die Bridge wird sich beenden, sobald der Installer übernimmt. Bitte dieses Fenster nicht manuell schließen."},
    "updates.available_top":    {"en": "⬆  Update available: {tag} — open release page",
                                 "de": "⬆  Update verfügbar: {tag} — Release-Seite öffnen"},
    "updates.installed":        {"en": "Installed: v{ver}",       "de": "Installiert: v{ver}"},
    "updates.balloon_title":    {"en": "SignalRGB Wallpaper update",
                                 "de": "SignalRGB-Wallpaper-Update"},
    "updates.balloon_msg":      {"en": "Version {tag} is available. Open the tray menu to view the release page.",
                                 "de": "Version {tag} ist verfügbar. Öffne das Tray-Menü um die Release-Seite zu öffnen."},
    # ── Effects submenu ─────────────────────────────────────────────
    "effects.ambient_label":    {"en": "Ambient effect",          "de": "Umgebungseffekt"},
    "effects.pixelfx_label":    {"en": "Pixelfx (cursor)",        "de": "Pixelfx (Cursor)"},
    "effects.tint_with_glow":   {"en": "Tint particles with glow colour",
                                 "de": "Partikel mit Glow-Farbe einfärben"},
    "ambient.off":              {"en": "Off",                     "de": "Aus"},
    "ambient.snow":             {"en": "Snow",                    "de": "Schnee"},
    "ambient.rain":             {"en": "Rain",                    "de": "Regen"},
    "ambient.sparks":           {"en": "Sparks",                  "de": "Funken"},
    "ambient.aurora":           {"en": "Aurora",                  "de": "Aurora"},
    "pixelfx.off":              {"en": "Off",                     "de": "Aus"},
    "pixelfx.trail":            {"en": "Mouse trail",             "de": "Mausspur"},
    "pixelfx.glow":             {"en": "Hover glow",              "de": "Cursor-Glow"},
    "pixelfx.ripple":           {"en": "Click ripple (needs Lively interaction)",
                                 "de": "Klick-Welle (benötigt Lively-Interaktion)"},
    "pixelfx.all":              {"en": "All combined",            "de": "Alle kombiniert"},
    # ── Widgets submenu ─────────────────────────────────────────────
    "widgets.edit_toggle":      {"en": "Edit widgets on this screen  ({state})",
                                 "de": "Widgets bearbeiten  ({state})"},
    "widgets.state.locked":     {"en": "locked",                  "de": "gesperrt"},
    "widgets.state.edit":       {"en": "EDIT MODE",               "de": "BEARBEITUNGSMODUS"},
    "widgets.placed_count":     {"en": "Currently placed: {n}",   "de": "Aktuell platziert: {n}"},
    "widgets.add_x":            {"en": "Add {label}",             "de": "{label} hinzufügen"},
    # ── About dialog ────────────────────────────────────────────────
    "about.title":              {"en": "About {app}",             "de": "Über {app}"},
    "about.version":            {"en": "Version {ver}",           "de": "Version {ver}"},
    "about.github_handle":      {"en": "@{user} on GitHub",       "de": "@{user} auf GitHub"},
    "about.copyright":          {"en": "© 2026 {author} · MIT Licensed",
                                 "de": "© 2026 {author} · MIT-Lizenz"},
    "about.tagline":            {"en": "Live SignalRGB-driven glow behind your wallpaper, with placeable widgets, ambient effects and a one-shot installer.",
                                 "de": "Live SignalRGB-gesteuertes Glow hinter deinem Wallpaper, mit platzierbaren Widgets, Umgebungseffekten und einem Ein-Klick-Installer."},
    "about.btn.github":         {"en": "Project on GitHub",       "de": "Projekt auf GitHub"},
    "about.btn.license":        {"en": "MIT License",             "de": "MIT-Lizenz"},
    "about.btn.credits":        {"en": "Open-source credits",     "de": "Open-Source-Credits"},
    "about.btn.donate":         {"en": "☕  Buy me a coffee (PayPal)",
                                 "de": "☕  Spendier mir einen Kaffee (PayPal)"},
    "about.btn.close":          {"en": "Close",                   "de": "Schließen"},
    # ── Relative-time helpers used by tray ──────────────────────────
    "ago.s":                    {"en": "{n}s ago",                "de": "vor {n}s"},
    "ago.m":                    {"en": "{n}m ago",                "de": "vor {n}min"},
    "ago.h":                    {"en": "{n}h ago",                "de": "vor {n}h"},
}

_CURRENT_LANG = "en"


def _detect_default_lang() -> str:
    """Return 'de' if the system locale starts with German, else 'en'."""
    try:
        loc = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""
        if loc.lower().startswith("de"):
            return "de"
    except Exception:
        pass
    env = (os.environ.get("LANG", "") or os.environ.get("LANGUAGE", "")).lower()
    if env.startswith("de"):
        return "de"
    return "en"


def init_language(config: dict) -> None:
    """Resolve the active language from config + system locale and stash it."""
    global _CURRENT_LANG
    pref = (config.get("language") or "auto").lower()
    if pref in ("en", "de"):
        _CURRENT_LANG = pref
    else:
        _CURRENT_LANG = _detect_default_lang()
    print(f"[i18n] language = {_CURRENT_LANG}")


def tr(key: str, **kwargs) -> str:
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    text = entry.get(_CURRENT_LANG) or entry.get("en") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def load_config() -> dict:
    p = config_path()
    if not p.exists():
        cfg = default_config()
        save_config(cfg)
        return cfg
    try:
        with p.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"[config] load failed ({e}); resetting to defaults")
        cfg = default_config()
        save_config(cfg)
        return cfg
    # Migrate / backfill so older configs gain new fields without erroring.
    cfg.setdefault("version", CONFIG_VERSION)
    cfg.setdefault("screenCount", 1)
    try:
        cfg["screenCount"] = max(1, min(N_SCREENS, int(cfg["screenCount"])))
    except (TypeError, ValueError):
        cfg["screenCount"] = 1
    cfg.setdefault("fullscreenPause", True)
    cfg["fullscreenPause"] = bool(cfg.get("fullscreenPause", True))
    cfg.setdefault("updateCheckEnabled", True)
    cfg["updateCheckEnabled"] = bool(cfg.get("updateCheckEnabled", True))
    cfg.setdefault("allowBetas", False)
    cfg["allowBetas"] = bool(cfg.get("allowBetas", False))
    cfg.setdefault("language", "auto")
    if cfg.get("language") not in ("auto", "en", "de"):
        cfg["language"] = "auto"
    cfg.setdefault("screens", {})
    for n in range(N_SCREENS):
        s = cfg["screens"].setdefault(str(n), {})
        for k, v in DEFAULT_SCREEN_SETTINGS.items():
            s.setdefault(k, v)
        # Pad / truncate the presets list to PRESET_SLOTS so a config
        # written by an older build (with no presets) gets the right
        # number of empty slots, and one from a future build with more
        # slots gets the surplus dropped (defensive, not critical).
        if not isinstance(s.get("presets"), list):
            s["presets"] = [None] * PRESET_SLOTS
        elif len(s["presets"]) < PRESET_SLOTS:
            s["presets"] = list(s["presets"]) + [None] * (PRESET_SLOTS - len(s["presets"]))
        elif len(s["presets"]) > PRESET_SLOTS:
            s["presets"] = list(s["presets"])[:PRESET_SLOTS]
    return cfg


def save_config(cfg: dict) -> None:
    p = config_path()
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    tmp.replace(p)


# ============================================================================
# WebSocket helpers
# ============================================================================

def parse_http_headers(raw: bytes) -> dict:
    headers = {}
    for line in raw.split(b"\r\n")[1:]:
        if b":" in line:
            k, _, v = line.partition(b":")
            headers[k.strip().lower()] = v.strip()
    return headers


def make_handshake(request: bytes) -> bytes | None:
    headers = parse_http_headers(request)
    if headers.get(b"upgrade", b"").lower() != b"websocket":
        return None
    key = headers.get(b"sec-websocket-key")
    if not key:
        return None
    accept = base64.b64encode(hashlib.sha1(key + WS_GUID).digest()).decode()
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    ).encode()


def _encode_frame(opcode: int, payload: bytes) -> bytes:
    header = bytearray([0x80 | (opcode & 0x0f)])  # FIN=1 + opcode
    n = len(payload)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += struct.pack(">H", n)
    else:
        header.append(127)
        header += struct.pack(">Q", n)
    return bytes(header) + payload


def encode_binary_frame(payload: bytes) -> bytes:
    return _encode_frame(0x2, payload)


def encode_text_frame(text: str) -> bytes:
    return _encode_frame(0x1, text.encode("utf-8"))


async def read_client_text_frame(reader) -> str | None:
    """Read one masked client→server WS frame; return its decoded text body
    if it's a text frame, None on close/control/error. Skips ping/pong and
    binary frames silently — the wallpaper page only ever sends JSON text
    messages back to the bridge."""
    try:
        header = await reader.readexactly(2)
    except (asyncio.IncompleteReadError, ConnectionError):
        return None
    b1, b2 = header[0], header[1]
    fin = (b1 & 0x80) != 0
    opcode = b1 & 0x0f
    masked = (b2 & 0x80) != 0
    n = b2 & 0x7f
    if n == 126:
        n = struct.unpack(">H", await reader.readexactly(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", await reader.readexactly(8))[0]
    # Browser → server frames MUST be masked per RFC 6455. Reject anything
    # else (defensive — should never happen with real browser clients).
    mask = await reader.readexactly(4) if masked else b"\x00\x00\x00\x00"
    payload = await reader.readexactly(n) if n else b""
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if opcode == 0x8:    # close
        return None
    if opcode == 0x9:    # ping — bridge ignores (no pong sent; browsers
        return ""        # don't currently ping us anyway)
    if opcode != 0x1:    # not text → caller skips
        return ""
    if not fin:
        # Wallpaper-page messages are tiny single-frame JSON blobs. Anything
        # fragmented gets dropped rather than reassembled.
        return ""
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return ""


# ============================================================================
# HTTP image proxy
# ============================================================================

def http_error(writer, code: int, message: str):
    body = message.encode("utf-8")
    status = {400: "Bad Request", 403: "Forbidden", 404: "Not Found",
              415: "Unsupported Media Type", 500: "Server Error"}.get(code, "Error")
    head = (
        f"HTTP/1.1 {code} {status}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Access-Control-Allow-Origin: *\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    writer.write(head + body)


def http_serve_image(writer, query: str):
    params = urllib.parse.parse_qs(query)
    raw_path = params.get("path", [""])[0]
    if not raw_path:
        return http_error(writer, 400, "missing 'path' query parameter")
    path = urllib.parse.unquote(raw_path)
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMAGE_EXTS:
        return http_error(writer, 415, f"unsupported extension: {ext or '(none)'}")
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        return http_error(writer, 404, f"file not found: {abs_path}")
    try:
        with open(abs_path, "rb") as f:
            data = f.read()
    except OSError as e:
        return http_error(writer, 403, f"cannot read file: {e}")
    content_type = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"
    head = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(data)}\r\n"
        f"Cache-Control: max-age=10\r\n"
        f"Access-Control-Allow-Origin: *\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    writer.write(head + data)


def parse_query_screen(target: str) -> int:
    if "?" not in target:
        return 0
    _, _, query = target.partition("?")
    params = urllib.parse.parse_qs(query)
    try:
        n = int(params.get("screen", ["0"])[0])
    except (TypeError, ValueError):
        return 0
    if n < 0 or n > MAX_SCREEN_INDEX:
        return 0
    return n


def parse_query_role(target: str) -> str:
    """Identify what kind of client opened this WS — `wallpaper` (the
    page Lively/WE renders, default for legacy clients) or
    `configurator` (the in-browser settings UI). The Status dialog
    counts only `wallpaper` clients so the user sees actual rendered
    pages, not their own open Configurator tab."""
    if "?" not in target:
        return "wallpaper"
    _, _, query = target.partition("?")
    params = urllib.parse.parse_qs(query)
    role = (params.get("role", ["wallpaper"])[0] or "wallpaper").lower()
    return role if role in ("wallpaper", "configurator") else "wallpaper"


# ============================================================================
# Broadcaster — UDP fan-out + settings push
# ============================================================================

class Broadcaster:
    """
    Routes UDP datagrams to WS clients filtered by screen-index, and pushes
    settings updates as JSON text frames. The asyncio loop drives all I/O;
    cross-thread calls (e.g. tray->push_settings) use call_soon_threadsafe.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, get_settings, get_screen_count, update_background, get_paused, on_widget_command):
        self.loop = loop
        self.get_settings = get_settings        # callable(screen:int)->dict
        self.get_screen_count = get_screen_count  # callable()->int (1..N_SCREENS)
        self.update_background = update_background  # callable(screen:int, png_bytes:bytes)->bool
        self.get_paused = get_paused            # callable()->bool (fullscreen-induced pause)
        self.on_widget_command = on_widget_command  # callable(screen:int, msg:dict)->None
        # The hwmon provider is wired in after construction (BridgeRuntime
        # builds the broadcaster before it builds the HwMonPoller). Stays
        # None until then; the /hwmon/sensors endpoint just reports
        # "online: false" if it's missing.
        self.hwmon_provider = None             # set externally; HwMonPoller
        self.clients_by_screen: dict[int, set] = {}
        self._lock = asyncio.Lock()

    def handle_client_message(self, screen: int, msg: dict):
        """Route a decoded JSON message from a wallpaper page. All widget
        mutations live here; future client→server messages slot in next to
        them. Runs on the asyncio loop thread."""
        t = msg.get("type")
        if t in ("widget-update", "widget-add", "widget-remove", "widgets-lock",
                 "setting-update", "viewport", "bridge-setting-update",
                 "preset-save", "preset-apply", "preset-clear",
                 "screen-reset",
                 "profile-add", "profile-update", "profile-remove"):
            try:
                self.on_widget_command(screen, msg)
            except Exception as e:
                print(f"[ws] command failed: {e}")
        # Unknown types are silently dropped — clients on a newer protocol
        # version shouldn't crash an older bridge.

    # ----- client lifecycle -----

    async def add(self, writer, screen: int, role: str = "wallpaper"):
        async with self._lock:
            self.clients_by_screen.setdefault(screen, set()).add(writer)
            # Side-table for client roles so the Status dialog can
            # count only the actual wallpaper pages and not e.g. the
            # user's own open Configurator tab.
            if not hasattr(self, "client_roles"):
                self.client_roles = {}
            self.client_roles[writer] = role
            total = sum(len(s) for s in self.clients_by_screen.values())
        print(f"[+] ws screen={screen} role={role} (total: {total})")
        # Push current settings immediately so the page can paint with the
        # right background / layout before the first frame arrives.
        try:
            settings = self.get_settings(screen)
            writer.write(encode_text_frame(json.dumps({
                "type": "settings", "screen": screen,
                "data": settings, "language": _CURRENT_LANG,
                "screenCount": int(self.get_screen_count()),
                "profiles": self._get_profiles_for_push(),
            })))
        except Exception as e:
            print(f"[ws] initial settings push failed: {e}")
        # Also push the current paused state so a page that connects mid-
        # game starts paused (rather than rendering a brief flash of glow
        # before the next state change fires).
        try:
            writer.write(encode_text_frame(json.dumps({"type": "paused", "paused": bool(self.get_paused())})))
        except Exception as e:
            print(f"[ws] initial paused push failed: {e}")

    async def remove(self, writer):
        async with self._lock:
            if hasattr(self, "client_roles"):
                self.client_roles.pop(writer, None)
            for screen, clients in list(self.clients_by_screen.items()):
                if writer in clients:
                    clients.discard(writer)
                    total = sum(len(s) for s in self.clients_by_screen.values())
                    try: writer.close()
                    except Exception: pass
                    print(f"[-] ws screen={screen} (total: {total})")
                    return

    # ----- broadcasting (called from asyncio loop) -----

    async def broadcast_frame(self, screen: int, payload: bytes):
        # Skip while paused — no point shipping per-frame UDP-derived
        # bytes when the wallpaper page is going to drop them anyway. The
        # plugin keeps sending, the bridge just absorbs.
        try:
            if self.get_paused():
                return
        except Exception:
            pass
        async with self._lock:
            clients = list(self.clients_by_screen.get(screen, ()))
        if not clients:
            return
        frame = encode_binary_frame(payload)
        dead = []
        for w in clients:
            try:
                w.write(frame)
            except Exception:
                dead.append(w)
        for w in dead:
            await self.remove(w)

    async def push_pause(self, paused: bool):
        msg = json.dumps({"type": "paused", "paused": bool(paused)})
        frame = encode_text_frame(msg)
        async with self._lock:
            all_clients = [w for clients in self.clients_by_screen.values() for w in clients]
        dead = []
        for w in all_clients:
            try:
                w.write(frame)
            except Exception:
                dead.append(w)
        for w in dead:
            await self.remove(w)
        if all_clients:
            print(f"[push] paused={paused} -> {len(all_clients)} client(s)")

    def push_pause_threadsafe(self, paused: bool):
        asyncio.run_coroutine_threadsafe(self.push_pause(paused), self.loop)

    async def push_settings(self, screen: int, settings: dict):
        async with self._lock:
            clients = list(self.clients_by_screen.get(screen, ()))
        if not clients:
            return
        # Surface the active UI language alongside the per-screen data so
        # the Configurator can localise itself off a single push.
        msg = json.dumps({"type": "settings", "screen": screen,
                          "data": settings, "language": _CURRENT_LANG,
                          "screenCount": int(self.get_screen_count()),
                          "profiles": self._get_profiles_for_push()})
        frame = encode_text_frame(msg)
        dead = []
        for w in clients:
            try:
                w.write(frame)
            except Exception:
                dead.append(w)
        for w in dead:
            await self.remove(w)
        print(f"[push] settings -> screen={screen} ({len(clients)} clients)")

    # ----- thread-safe entry from non-asyncio threads (tray callback) -----

    def push_settings_threadsafe(self, screen: int, settings: dict):
        asyncio.run_coroutine_threadsafe(self.push_settings(screen, settings), self.loop)

    def _get_profiles_for_push(self) -> list:
        """Pull the latest profiles list from the runtime config. Returns
        an empty list when the runtime hasn't been wired in yet (defensive
        — the Broadcaster's request handlers and the WS-open path can fire
        before bridge_runtime is set in start())."""
        rt = getattr(self, "bridge_runtime", None)
        if rt is None:
            return []
        try:
            with rt.config_lock:
                return list(rt.config.get("profiles", []) or [])
        except Exception:
            return []

    async def push_sysstats(self, snapshot: dict):
        """Broadcast a single sysstats payload to every connected client.
        snapshot keys: cpu (0..100), ram (0..100), netDown / netUp (bytes/s),
        uptime (seconds), and 'ts' (epoch ms).
        """
        msg = json.dumps({"type": "sysstats", "data": snapshot})
        frame = encode_text_frame(msg)
        async with self._lock:
            all_clients = [w for clients in self.clients_by_screen.values() for w in clients]
        dead = []
        for w in all_clients:
            try: w.write(frame)
            except Exception: dead.append(w)
        for w in dead:
            await self.remove(w)

    def push_sysstats_threadsafe(self, snapshot: dict):
        asyncio.run_coroutine_threadsafe(self.push_sysstats(snapshot), self.loop)

    # ----- TCP accept handler (HTTP or WS upgrade) -----

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError):
            writer.close()
            return

        headers = parse_http_headers(request)
        first_line = request.split(b"\r\n", 1)[0].decode("latin1", "replace")
        parts = first_line.split(" ", 2)
        method = parts[0] if len(parts) >= 1 else ""
        target = parts[1] if len(parts) >= 2 else ""

        if headers.get(b"upgrade", b"").lower() == b"websocket":
            return await self._serve_websocket(reader, writer, request, target)

        if method == "GET" and target.startswith("/image"):
            query = target.split("?", 1)[1] if "?" in target else ""
            try:
                http_serve_image(writer, query)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        # The SignalRGB plugin XHRs here on every Update() tick to learn how
        # many controllers to announce. Plugin sandbox has no service-level
        # settings UI, so the bridge owns this knob — change it via tray.
        # Match `/config` exactly (with optional query string) — `startswith`
        # would otherwise eat `/configurator` and silently serve JSON in its
        # place.
        if method == "GET" and target.split("?", 1)[0] in ("/config", "/config/"):
            try:
                # The plugin uses screenCount to decide how many virtual
                # controllers to announce. The per-screen viewport[] sidecar
                # lets the plugin auto-derive a matching grid aspect ratio
                # — e.g. 3840×1080 ultrawide gets cols≈3.56×rows instead of
                # a square — so the SignalRGB device's effect samples scale
                # to the actual monitor instead of always being square.
                count = int(self.get_screen_count())
                screens = []
                for i in range(count):
                    try:
                        s = self.get_settings(i)
                        m = s.get("mirrorOf")
                        screens.append({
                            "viewportW": int(s.get("viewportW") or 0),
                            "viewportH": int(s.get("viewportH") or 0),
                            # bgImage is included so the Configurator's
                            # Overview card can paint mini-thumbnails for
                            # every screen without opening a WS per tab.
                            "bgImage":   str(s.get("bgImage") or ""),
                            # mirrorOf surfaces in the overview as a small
                            # indicator on mirroring tiles.
                            "mirrorOf":  (int(m) if isinstance(m, int) else None),
                        })
                    except Exception:
                        screens.append({"viewportW": 0, "viewportH": 0,
                                        "bgImage": "", "mirrorOf": None})
                payload = json.dumps({
                    "screenCount": count,
                    "screens": screens,
                    "language": _CURRENT_LANG,
                }).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        # POST /screen/<N>/background — receive a PNG from the builder
        # and apply it as that screen's background. Body is the raw PNG
        # bytes (no multipart wrapper; Content-Type: image/png). We
        # save with a millisecond-timestamped filename so the wallpaper
        # page re-fetches a fresh URL (avoids stale-image cache hits).
        if method == "POST" and target.startswith("/screen/"):
            parts = target.split("?", 1)[0].strip("/").split("/")
            # ["screen", "<N>", "background"]
            if len(parts) >= 3 and parts[0] == "screen" and parts[2] == "background":
                try:
                    screen_idx = int(parts[1])
                except ValueError:
                    screen_idx = -1
                if 0 <= screen_idx < N_SCREENS:
                    try:
                        content_length = int(headers.get(b"content-length", b"0") or 0)
                    except ValueError:
                        content_length = 0
                    if 0 < content_length <= MAX_BACKGROUND_UPLOAD_BYTES:
                        try:
                            body = await reader.readexactly(content_length)
                            ok = self.update_background(screen_idx, body)
                            if ok:
                                await self.push_settings(screen_idx, self.get_settings(screen_idx))
                                payload = b'{"ok":true}'
                            else:
                                payload = b'{"ok":false}'
                            head = (
                                "HTTP/1.1 200 OK\r\n"
                                "Content-Type: application/json\r\n"
                                f"Content-Length: {len(payload)}\r\n"
                                "Cache-Control: no-store\r\n"
                                "Connection: close\r\n\r\n"
                            ).encode()
                            writer.write(head + payload)
                        except asyncio.IncompleteReadError:
                            http_error(writer, 400, "incomplete body")
                        except Exception as e:
                            http_error(writer, 500, f"upload failed: {e}")
                    else:
                        http_error(writer, 400, f"bad content-length: {content_length} (max {MAX_BACKGROUND_UPLOAD_BYTES})")
                else:
                    http_error(writer, 404, f"unknown screen index: {screen_idx} (allowed 0..{N_SCREENS-1})")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return

        # POST /screen/<N>/settings — body is JSON {key1: val1, key2: val2}
        # for a batch setting update on screen N. Used by the Configurator's
        # "Apply to all screens" buttons: the open WS is bound to one
        # screen, so cross-screen updates need an out-of-band channel.
        # Each key is filtered through the same _SETTABLE_SCREEN_KEYS
        # whitelist `setting-update` uses, so the HTTP path can't grow
        # the attack surface past what the WS already exposes.
        if method == "POST" and target.startswith("/screen/"):
            parts2 = target.split("?", 1)[0].strip("/").split("/")
            if len(parts2) >= 3 and parts2[0] == "screen" and parts2[2] == "settings":
                try:
                    screen_idx = int(parts2[1])
                except ValueError:
                    screen_idx = -1
                if 0 <= screen_idx < N_SCREENS:
                    try:
                        content_length = int(headers.get(b"content-length", b"0") or 0)
                    except ValueError:
                        content_length = 0
                    if not (0 < content_length <= 65536):
                        http_error(writer, 400, f"bad content-length: {content_length}")
                        try: await writer.drain()
                        except Exception: pass
                        try: writer.close()
                        except Exception: pass
                        return
                    try:
                        body = await reader.readexactly(content_length)
                        req = json.loads(body.decode("utf-8"))
                        if not isinstance(req, dict):
                            raise ValueError("body must be a JSON object")
                        applied = 0
                        for key, value in req.items():
                            snap = self.update_screen_setting(screen_idx, str(key), value)
                            if snap is not None:
                                applied += 1
                        payload = json.dumps({"ok": True, "applied": applied}).encode("utf-8")
                        head = (
                            "HTTP/1.1 200 OK\r\n"
                            "Content-Type: application/json\r\n"
                            f"Content-Length: {len(payload)}\r\n"
                            "Cache-Control: no-store\r\n"
                            "Connection: close\r\n\r\n"
                        ).encode()
                        writer.write(head + payload)
                    except asyncio.IncompleteReadError:
                        http_error(writer, 400, "incomplete body")
                    except Exception as e:
                        http_error(writer, 500, f"settings update failed: {e}")
                else:
                    http_error(writer, 404, f"unknown screen index: {screen_idx}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return

        # Local in-browser wallpaper builder. Opened via the tray "Build
        # Wallpaper…" menu item. Pure client-side canvas app — we just
        # serve the static HTML file bundled alongside the exe.
        if method == "GET" and target.split("?", 1)[0] in ("/builder", "/builder/"):
            try:
                builder_path = _resource_path("builder.html")
                data = builder_path.read_bytes()
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    f"Content-Length: {len(data)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + data)
            except FileNotFoundError:
                http_error(writer, 500, "builder.html not bundled with this build")
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        # Wallpaper library: list + individual file. Files live under
        # %LOCALAPPDATA%\SignalRGBWallpaper\library\ — the installer drops
        # the generated starter set there on install, and the user can
        # also add their own PNGs by hand. `library.json` carries
        # metadata (label, thumb path, etc.); the listing endpoint just
        # streams that file. Individual /library/<name> serves the PNG /
        # thumb bytes back; the Configurator builds img URLs off this
        # path. Path traversal is blocked by rejecting any name with a
        # path separator or dot-dot.
        # /hwmon/sensors — flat list of every sensor LibreHardwareMonitor
        # is reporting, plus a small status block. The Configurator's
        # hardware-sensor widget options modal calls this to populate
        # the sensor-path dropdown. Returns an empty list when LHM
        # isn't running (status.online = false).
        if method == "GET" and target.split("?", 1)[0] == "/hwmon/sensors":
            try:
                hw = getattr(self, "hwmon_provider", None)
                snap = hw.get_snapshot() if hw else {}
                status = hw.get_status() if hw else {"online": False, "sensorCount": 0}
                items = [
                    {"path": p, "value": entry.get("value"),
                     "unit": entry.get("unit"), "raw": entry.get("raw")}
                    for p, entry in sorted(snap.items())
                ]
                payload = json.dumps({"status": status, "items": items}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        if method == "GET" and target.split("?", 1)[0] == "/library/list":
            try:
                lib_dir = library_dir()
                cat_path = lib_dir / "library.json"
                if cat_path.exists():
                    payload = cat_path.read_bytes()
                else:
                    payload = b'{"version":1,"items":[]}'
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return
        if method == "GET" and target.split("?", 1)[0].startswith("/library/"):
            name = target.split("?", 1)[0][len("/library/"):]
            if not name or "/" in name or "\\" in name or ".." in name:
                http_error(writer, 400, "bad library filename")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                fp = library_dir() / name
                if not fp.exists() or not fp.is_file():
                    http_error(writer, 404, "library item not found")
                else:
                    body = fp.read_bytes()
                    ct, _ = mimetypes.guess_type(str(fp))
                    if not ct: ct = "application/octet-stream"
                    head = (
                        "HTTP/1.1 200 OK\r\n"
                        f"Content-Type: {ct}\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        "Cache-Control: public, max-age=86400\r\n"
                        "Access-Control-Allow-Origin: *\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode()
                    writer.write(head + body)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        # POST /library/upload — body is the raw PNG; query string carries
        # ?name=<label>. We slug the label, drop into the user-writable
        # library dir, regenerate library.json so future /library/list
        # calls include the new entry. Bytes capped via the same
        # MAX_BACKGROUND_UPLOAD_BYTES the screen uploader uses.
        if method == "POST" and target.split("?", 1)[0] == "/library/upload":
            qs = target.split("?", 1)[1] if "?" in target else ""
            params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            label = urllib.parse.unquote(params.get("name", "Untitled")).strip() or "Untitled"
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= MAX_BACKGROUND_UPLOAD_BYTES):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                # Reject anything that doesn't look like a PNG/JPEG/WebP.
                if not (body[:8] == b"\x89PNG\r\n\x1a\n" or body[:3] == b"\xff\xd8\xff"
                        or body[:4] == b"RIFF"):
                    http_error(writer, 400, "unsupported image format")
                    try: await writer.drain()
                    except Exception: pass
                    try: writer.close()
                    except Exception: pass
                    return
                slug = _library_slug(label, library_dir())
                ext = ".png"
                if body[:3] == b"\xff\xd8\xff": ext = ".jpg"
                elif body[:4] == b"RIFF":       ext = ".webp"
                fp = library_dir() / (slug + ext)
                fp.write_bytes(body)
                _library_rebuild_catalogue(library_dir())
                payload = json.dumps({"ok": True, "id": slug, "file": fp.name}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 500, f"upload failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        # DELETE /library/<name> — removes the file + its thumbnail (if any)
        # + regenerates library.json. Same path-traversal protections as the
        # GET handler. We only delete inside library_dir(); no risk of
        # walking out via dots or separators.
        if method == "DELETE" and target.split("?", 1)[0].startswith("/library/"):
            name = target.split("?", 1)[0][len("/library/"):]
            if not name or "/" in name or "\\" in name or ".." in name:
                http_error(writer, 400, "bad library filename")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                lib = library_dir()
                fp = lib / name
                if fp.exists() and fp.is_file():
                    fp.unlink()
                # Also drop a sibling .thumb.png if present (matches our
                # generator's naming) — try both <name>.thumb.png and
                # <stem>.thumb.png since the file extension might differ.
                stem = fp.stem
                if stem.endswith(".thumb"): stem = stem[:-len(".thumb")]
                for cand in (lib / (stem + ".thumb.png"), lib / (fp.name + ".thumb")):
                    try:
                        if cand.exists(): cand.unlink()
                    except Exception: pass
                _library_rebuild_catalogue(lib)
                payload = b'{"ok":true}'
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"delete failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        # POST /library/pin — body is JSON {"file": "...", "pinned": bool}.
        # Toggles the pin flag on a library entry without re-scanning the
        # directory; the Configurator's right-click Pin/Unpin menu hits
        # this. Returns the updated entry.
        if method == "POST" and target.split("?", 1)[0] == "/library/pin":
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= 8192):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                req = json.loads(body.decode("utf-8"))
                file = str(req.get("file", ""))
                pinned = bool(req.get("pinned", False))
                if not file or "/" in file or "\\" in file or ".." in file:
                    http_error(writer, 400, "bad file name")
                    try: await writer.drain()
                    except Exception: pass
                    try: writer.close()
                    except Exception: pass
                    return
                updated = _library_update_item(
                    library_dir(), file, lambda it: it.update({"pinned": pinned})
                )
                if updated is None:
                    http_error(writer, 404, f"library entry not found: {file}")
                else:
                    payload = json.dumps({"ok": True, "item": updated}).encode("utf-8")
                    head = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(payload)}\r\n"
                        "Cache-Control: no-store\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode()
                    writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 500, f"pin failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        # POST /library/reorder — body is JSON {"order": ["a.png", "b.png", ...]}.
        # Assigns sequential `order` indices to matching entries. The
        # Configurator drags-and-drops tiles in the Library strip and
        # POSTs the new order here.
        if method == "POST" and target.split("?", 1)[0] == "/library/reorder":
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= 65536):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                req = json.loads(body.decode("utf-8"))
                raw_order = req.get("order", [])
                if not isinstance(raw_order, list):
                    raise ValueError("`order` must be a list")
                order = []
                for f in raw_order:
                    s = str(f)
                    if not s or "/" in s or "\\" in s or ".." in s:
                        raise ValueError(f"bad file name in order: {s!r}")
                    order.append(s)
                n = _library_apply_order(library_dir(), order)
                payload = json.dumps({"ok": True, "applied": n}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 500, f"reorder failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        # GET /backup — stream a ZIP of every piece of user state
        # (config.json + library/ + screens/). Browser-driven download.
        if method == "GET" and target.split("?", 1)[0] == "/backup":
            try:
                bridge_runtime = getattr(self, "bridge_runtime", None) or self
                data = bridge_runtime.build_backup_zip()
                stamp = time.strftime("%Y%m%d-%H%M%S")
                filename = f"signalrgb-wallpaper-backup-{stamp}.zip"
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/zip\r\n"
                    f"Content-Length: {len(data)}\r\n"
                    f"Content-Disposition: attachment; filename=\"{filename}\"\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + data)
            except Exception as e:
                http_error(writer, 500, f"backup failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        # POST /restore — body is the raw ZIP. Replaces config.json,
        # merges library/ + screens/ files on top of the existing dirs,
        # then pushes fresh settings to every connected wallpaper page.
        if method == "POST" and target.split("?", 1)[0] == "/restore":
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= 100 * 1024 * 1024):  # 100 MB cap
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                bridge_runtime = getattr(self, "bridge_runtime", None) or self
                report = bridge_runtime.restore_backup_zip(body)
                payload = json.dumps({"ok": True, **report}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except ValueError as e:
                http_error(writer, 400, f"restore rejected: {e}")
            except Exception as e:
                http_error(writer, 500, f"restore failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        # In-browser help page — scenario-based walkthroughs (1/2/3/4
        # monitors × Lively / Wallpaper Engine). Static HTML; pulls the
        # active language from /config like the Builder does. Images
        # under /help/images/* served from a sibling folder so the
        # maintainer can drop screenshots in by hand.
        if method == "GET" and target.split("?", 1)[0] in ("/help", "/help/"):
            try:
                help_path = _resource_path("help.html")
                data = help_path.read_bytes()
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    f"Content-Length: {len(data)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + data)
            except FileNotFoundError:
                http_error(writer, 500, "help.html not bundled with this build")
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return
        # /help/images/<file> — optional screenshots the maintainer can
        # drop into wallpaper_bridge/help_assets/ (dev) or
        # %LOCALAPPDATA%\SignalRGBWallpaper\help_images\ (post-install).
        # Path-traversal protected like /library.
        if method == "GET" and target.split("?", 1)[0].startswith("/help/images/"):
            name = target.split("?", 1)[0][len("/help/images/"):]
            if not name or "/" in name or "\\" in name or ".." in name:
                http_error(writer, 400, "bad help-image filename")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                # Prefer the user-writable %LOCALAPPDATA% copy so users can
                # add their own screenshots without rebuilding the bridge.
                user_dir = config_path().parent / "help_images"
                dev_dir  = Path(__file__).resolve().parent / "help_assets"
                fp = None
                for cand in (user_dir / name, dev_dir / name):
                    if cand.exists() and cand.is_file():
                        fp = cand; break
                if fp is None:
                    http_error(writer, 404, "help image not found")
                else:
                    body = fp.read_bytes()
                    ct, _ = mimetypes.guess_type(str(fp))
                    if not ct: ct = "application/octet-stream"
                    head = (
                        "HTTP/1.1 200 OK\r\n"
                        f"Content-Type: {ct}\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        "Cache-Control: public, max-age=86400\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode()
                    writer.write(head + body)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        # In-browser configurator — replaces the tray's per-screen widget /
        # effect submenus with a rich tabbed UI. Same WS protocol as the
        # wallpaper page; sends `setting-update` / `widget-*` commands.
        if method == "GET" and target.split("?", 1)[0] in ("/configurator", "/configurator/"):
            try:
                cfg_path = _resource_path("configurator.html")
                data = cfg_path.read_bytes()
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    f"Content-Length: {len(data)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + data)
            except FileNotFoundError:
                http_error(writer, 500, "configurator.html not bundled with this build")
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

        http_error(writer, 404, "not found")
        try: await writer.drain()
        except Exception: pass
        try: writer.close()
        except Exception: pass

    async def _serve_websocket(self, reader, writer, request, target):
        response = make_handshake(request)
        if not response:
            writer.close()
            return
        writer.write(response)
        await writer.drain()
        screen = parse_query_screen(target)
        role = parse_query_role(target)
        await self.add(writer, screen, role)
        try:
            while not writer.is_closing():
                text = await read_client_text_frame(reader)
                if text is None:    # close / EOF
                    break
                if not text:        # ignored frame type (binary, control, fragmented)
                    continue
                try:
                    msg = json.loads(text)
                except Exception:
                    continue
                self.handle_client_message(screen, msg)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError):
            pass
        finally:
            await self.remove(writer)


class HwMonPoller:
    """Optionally polls LibreHardwareMonitor's built-in HTTP server
    (default `http://localhost:8085/data.json`) for the full sensor tree
    — CPU / GPU / mainboard temps, fan RPMs, voltages, drive temps and
    power readings that psutil doesn't expose on its own.

    LHM ships with a "Remote Web Server" toggle (Options → Remote Web
    Server) that has to be on for this to work. If the user hasn't
    installed LHM or hasn't enabled the server, we just skip — the rest
    of the sysstats payload still ships, our hardware-sensor widgets
    show `--` placeholders.

    LHM's JSON is a deeply nested {id, Text, Value, Children} tree. We
    flatten it to a `path: value` dict keyed by the slash-separated path
    from the root (e.g. "AMD Ryzen 7 5800X / Temperatures / Core
    (Tctl/Tdie)"), parsing the `Value` field's numeric prefix so the
    wallpaper page can plot it as a sparkline. The original unit
    (°C / RPM / V / W / %) is captured alongside so widgets can label
    correctly without re-guessing.

    License: LibreHardwareMonitor is MPL 2.0 — we don't bundle it, only
    talk to its REST server when the user has it running, so no MPL
    propagation into our MIT distribution.
    """

    DEFAULT_URL = "http://localhost:8085/data.json"
    POLL_INTERVAL_S = 1.0
    REQUEST_TIMEOUT_S = 0.8

    def __init__(self):
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # path -> {"value": float, "raw": "45.5 °C", "unit": "°C"}
        self._snapshot: dict[str, dict] = {}
        self._last_ok_ts: float = 0.0
        self._last_error: str = ""
        # Size of the last payload we received from LHM, for the
        # "server reachable but 0 sensors parsed" diagnostic that the
        # Configurator's sensor-picker surfaces in its placeholder
        # option.
        self._last_payload_bytes: int = 0
        # Print a one-time hint when we first see a non-empty payload
        # produce zero sensors — so the bridge log carries a copy of
        # the JSON's root keys for the dev to look at, without
        # spamming the log every poll.
        self._warned_about_empty_parse = False

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="hwmon-poll").start()
        print(f"[hwmon] poller running (target {self.DEFAULT_URL}, "
              f"{self.POLL_INTERVAL_S} Hz). Optional: requires "
              "LibreHardwareMonitor with Remote Web Server enabled.")

    def stop(self):
        self._stop.set()

    def get_snapshot(self) -> dict:
        with self._lock:
            return dict(self._snapshot)

    def get_status(self) -> dict:
        """Tiny status object for the Configurator's 'LHM detected?'
        hint. Reports whether we last reached LHM, how long ago, and a
        sensor count for sanity."""
        with self._lock:
            return {
                "online":     bool(self._last_ok_ts) and
                              (time.time() - self._last_ok_ts) < 5,
                "lastOkTs":   int(self._last_ok_ts * 1000),
                "sensorCount": len(self._snapshot),
                "lastError":  self._last_error,
                "lastPayloadBytes": self._last_payload_bytes,
            }

    def _run(self):
        while not self._stop.is_set():
            try:
                req = urllib.request.Request(self.DEFAULT_URL,
                                              headers={"User-Agent": "SignalRGBBridge"})
                with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT_S) as resp:
                    payload = resp.read()
                tree = json.loads(payload)
                flat = self._flatten(tree)
                with self._lock:
                    self._snapshot = flat
                    self._last_ok_ts = time.time()
                    self._last_payload_bytes = len(payload)
                    if flat:
                        self._last_error = ""
                    else:
                        # We reached LHM, got a payload, but parsed zero
                        # sensors. Most likely the tree shape is
                        # different from what _flatten walks. Surface it
                        # so the Configurator's sensor-picker tells the
                        # user instead of just listing zero items.
                        self._last_error = "parsed 0 sensors from response"
                        if not self._warned_about_empty_parse:
                            self._warned_about_empty_parse = True
                            try:
                                top_keys = list(tree.keys())[:6]
                                child0 = (tree.get("Children") or [{}])[0]
                                child0_keys = list(child0.keys())[:6]
                                print(f"[hwmon] reachable but parsed 0 sensors from "
                                      f"{len(payload)} B. Root keys: {top_keys}, "
                                      f"first-child keys: {child0_keys}, "
                                      f"first-child Text: {child0.get('Text')!r}")
                            except Exception:
                                print(f"[hwmon] reachable but parsed 0 sensors from "
                                      f"{len(payload)} B (and dumping diagnostics failed)")
            except urllib.error.URLError:
                # Connection refused = LHM server not running. Don't
                # spam the log; just clear the snapshot so widgets show
                # placeholders instead of stale data.
                with self._lock:
                    if self._snapshot:
                        self._snapshot = {}
                    self._last_error = "offline"
            except Exception as e:
                with self._lock:
                    self._last_error = str(e)[:120]
            if self._stop.wait(self.POLL_INTERVAL_S):
                return

    # ── JSON flattening ────────────────────────────────────────────────
    # LHM's tree shape varies by build but the leaves are always
    # nodes with a "Value" string like "45.5 °C" / "1234 RPM" /
    # "0.92 V". The non-leaf wrappers (the outer "Sensor" node, the
    # per-host computer name node, device / category groupings) carry
    # an empty Value (or a non-numeric string like "Min", "Max").
    #
    # Rather than hard-coding the depth we just recurse from the root,
    # treat any node that parses as a number as a sensor, and build
    # paths from one level below the root (so we don't prefix every
    # sensor with "Sensor /"). The "Computer / DESKTOP-…" wrapper
    # stays in the path; with multiple PCs streaming into one LHM
    # instance the per-host prefix is actually useful, and on a
    # single-machine setup it's just one extra segment we accept.
    #
    # Numbers may use comma decimals on de_DE locales — handled by
    # _NUM_RE replacing "," with "." before float().

    _NUM_RE = re.compile(r"^([-+]?\d+(?:[.,]\d+)?)\s*(.*)$")

    @classmethod
    def _flatten(cls, tree: dict) -> dict:
        out: dict[str, dict] = {}
        # Walk every immediate child of the root. The root usually has
        # Text="Sensor"; its children are the per-host computer
        # wrappers. We skip the root's own Text but recurse from one
        # level below so the path doesn't lead with "Sensor / …".
        for child in (tree.get("Children") or []):
            cls._walk(child, [], out)
        return out

    @classmethod
    def _walk(cls, node: dict, path: list, out: dict) -> None:
        text = node.get("Text") or "?"
        new_path = path + [text]
        kids = node.get("Children") or []
        raw_value = node.get("Value")
        # Treat any node whose Value parses as a number as a sensor
        # leaf. Don't return after — wrappers technically CAN carry a
        # Value (LHM sometimes echoes a summary value on a parent) but
        # we still want to walk their children. The full path includes
        # this node's own Text segment because the "Sensor" root is
        # already stripped one level up.
        if raw_value:
            m = cls._NUM_RE.match(str(raw_value).strip())
            if m:
                num_str = m.group(1).replace(",", ".")
                try:
                    val = float(num_str)
                except ValueError:
                    val = None
                unit = m.group(2).strip()
                if val is not None:
                    out[" / ".join(new_path)] = {
                        "value": round(val, 2),
                        "raw":   str(raw_value),
                        "unit":  unit,
                    }
        for kid in kids:
            cls._walk(kid, new_path, out)


class NowPlayingPoller:
    """Watches Windows' SystemMediaTransportControls for the active
    media session and publishes `{title, artist, album, paused,
    position, duration, ts}` so the now-playing widget can render
    whatever's playing. Works with Spotify, Groove, Chrome+YouTube,
    Edge, anything that registers an SMTC session.

    Implementation: a dedicated asyncio loop on a daemon thread polls
    `SMTCManager.request_async() → get_current_session()` every
    second and runs `try_get_media_properties_async()`. The result is
    cached in `_snapshot` and read lock-free by the sysstats poller
    (single-writer / multiple-reader, dict-replace is atomic in
    CPython).

    When the `winrt-Windows.Media.Control` package isn't bundled
    (e.g. dev runs without optional deps), start() prints a notice and
    the snapshot stays empty — sysstats just won't include
    `nowPlaying` and the widget renders its `--` placeholder.
    """

    POLL_INTERVAL_S = 1.0

    def __init__(self):
        self._stop     = threading.Event()
        self._snapshot: dict = {}
        self._thread: threading.Thread | None = None
        self._available = False
        try:
            # Detect optional deps once at construction so we don't
            # eat the import cost on every poll if they're missing.
            import winrt.windows.media.control  # noqa: F401
            self._available = True
        except Exception as e:
            print(f"[nowplaying] winrt missing — widget will show n/a ({e})")

    def start(self):
        if not self._available:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="nowplaying-poll")
        self._thread.start()
        print("[nowplaying] poller running (1 Hz)")

    def stop(self):
        self._stop.set()

    def get_snapshot(self) -> dict:
        # CPython dict-attr read is atomic; no lock needed.
        return self._snapshot

    def _run(self):
        # Dedicated asyncio loop so we can await the SMTC API without
        # nesting on the main bridge loop.
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        except Exception as e:
            print(f"[nowplaying] loop init failed: {e}")
            return
        try:
            while not self._stop.is_set():
                try:
                    snap = loop.run_until_complete(self._tick())
                    if snap is not None:
                        self._snapshot = snap
                except Exception as e:
                    # Keep going even when SMTC throws — common during
                    # session-switch (track change), the next tick recovers.
                    if not isinstance(e, asyncio.CancelledError):
                        print(f"[nowplaying] tick failed: {e}")
                if self._stop.wait(self.POLL_INTERVAL_S):
                    return
        finally:
            try: loop.close()
            except Exception: pass

    async def _tick(self) -> dict | None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as _Mgr,
        )
        mgr = await _Mgr.request_async()
        session = mgr.get_current_session()
        if session is None:
            return {}   # no media playing
        try:
            props = await session.try_get_media_properties_async()
        except Exception:
            props = None
        playback = session.get_playback_info()
        timeline = session.get_timeline_properties()
        # PlaybackStatus enum: 0=Closed, 1=Opened, 2=Changing, 3=Stopped,
        # 4=Playing, 5=Paused. We only care "playing now?" — anything
        # other than 4 counts as paused for the widget's pause icon.
        playing = int(getattr(playback, "playback_status", 0)) == 4
        # winrt's timespan exposes total_seconds() in newer builds; on
        # older ones it's a python timedelta. Both have .total_seconds.
        def _secs(x) -> float:
            if x is None:
                return 0.0
            try: return float(x.total_seconds())
            except Exception:
                try: return float(x.duration.total_seconds())
                except Exception: return 0.0
        return {
            "title":    (getattr(props, "title", "") or "") if props else "",
            "artist":   (getattr(props, "artist", "") or "") if props else "",
            "album":    (getattr(props, "album_title", "") or "") if props else "",
            "paused":   (not playing),
            "position": _secs(getattr(timeline, "position", None)),
            "duration": _secs(getattr(timeline, "end_time", None)),
            "ts":       int(time.time() * 1000),
        }


class SysStatsPoller:
    """Polls CPU / RAM / network counters via psutil once per second on its
    own daemon thread and pushes a snapshot through Broadcaster.push_sysstats.
    Disables itself (no-op) when psutil isn't available so the rest of the
    bridge still runs.

    Optionally merges in an `hwmon` dict from a sibling HwMonPoller so
    the wallpaper page sees CPU/GPU temps, fan RPMs and voltages in the
    same payload its existing CPU/RAM widgets already drain."""

    def __init__(self, broadcaster: 'Broadcaster',
                 hwmon: 'HwMonPoller | None' = None,
                 nowplaying: 'NowPlayingPoller | None' = None):
        self.broadcaster = broadcaster
        self.hwmon = hwmon
        self.nowplaying = nowplaying
        self._stop = threading.Event()
        self._last_net = None       # (sent, recv) from previous tick
        self._last_net_ts = 0.0
        self._boot_time = time.time()
        if _HAS_PSUTIL:
            try:
                self._boot_time = psutil.boot_time()
            except Exception:
                pass

    def start(self):
        if not _HAS_PSUTIL:
            print("[sysstats] psutil missing — CPU / RAM / Net widgets will show 'n/a'")
            return
        threading.Thread(target=self._run, daemon=True, name="sysstats-poll").start()
        print("[sysstats] poller running (1 Hz)")

    def stop(self):
        self._stop.set()

    def _run(self):
        # Seed the per-CPU sampler so the first reading isn't a misleading 0
        # (psutil.cpu_percent compares against a previous probe).
        try: psutil.cpu_percent(interval=None)
        except Exception: pass
        while not self._stop.is_set():
            try:
                snap = self._collect()
                self.broadcaster.push_sysstats_threadsafe(snap)
            except Exception as e:
                print(f"[sysstats] tick failed: {e}")
            if self._stop.wait(1.0):
                return

    def _collect(self) -> dict:
        cpu = float(psutil.cpu_percent(interval=None))
        mem = psutil.virtual_memory()
        ram = float(mem.percent)
        # net_io_counters is monotonically increasing; derive a rate by
        # diffing against the previous sample. First call yields 0 since
        # we have no baseline yet.
        now = time.monotonic()
        net = psutil.net_io_counters()
        if self._last_net and self._last_net_ts:
            dt = max(1e-3, now - self._last_net_ts)
            net_down = max(0.0, (net.bytes_recv - self._last_net[0]) / dt)
            net_up   = max(0.0, (net.bytes_sent - self._last_net[1]) / dt)
        else:
            net_down = 0.0
            net_up   = 0.0
        self._last_net    = (net.bytes_recv, net.bytes_sent)
        self._last_net_ts = now
        snap = {
            "cpu":     round(cpu, 1),
            "ram":     round(ram, 1),
            "netDown": round(net_down, 0),
            "netUp":   round(net_up, 0),
            "uptime":  int(time.time() - self._boot_time),
            "ts":      int(time.time() * 1000),
        }
        if self.hwmon is not None:
            # Per-sensor sub-dict: { "AMD Ryzen … / Temperatures / Core …":
            # { value, raw, unit }, … }. Empty when LHM isn't running so
            # widgets can show their `--` placeholder instead of stale data.
            snap["hwmon"] = self.hwmon.get_snapshot()
        if self.nowplaying is not None:
            np_snap = self.nowplaying.get_snapshot()
            if np_snap:
                snap["nowPlaying"] = np_snap
        return snap


class CycleScheduler:
    """Per-screen background poller that flips the active wallpaper to
    the next library entry every `cycle.intervalMin` minutes when
    enabled. Runs as a single thread that wakes every 30 s and walks
    every active screen — cheap because each screen's check is just a
    config read and a wall-clock compare.

    Mirror screens are skipped explicitly: the source's cycle drives
    their bgImage via the existing `_replicate_to_mirrors` path, so
    running the cycle twice would just thrash the mirror with extra
    file writes.
    """

    POLL_INTERVAL_S = 30.0

    def __init__(self, bridge_runtime):
        self.bridge = bridge_runtime
        self._stop  = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="cycle-scheduler")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        # First tick fires after one POLL_INTERVAL so a freshly-started
        # bridge doesn't immediately shuffle on top of whatever the
        # user last set manually.
        while not self._stop.wait(self.POLL_INTERVAL_S):
            try:
                self._tick()
            except Exception as e:
                print(f"[cycle] tick crashed: {e}")

    def _tick(self):
        now_ms = int(time.time() * 1000)
        screen_count = int(self.bridge.get_screen_count())
        for i in range(screen_count):
            try:
                with self.bridge.config_lock:
                    s = self.bridge.config.get("screens", {}).get(str(i))
                    if not isinstance(s, dict):
                        continue
                    cycle = s.get("cycle") or {}
                    if not cycle.get("enabled"):
                        continue
                    if s.get("mirrorOf") is not None:
                        continue
                    interval_ms = max(60_000,
                                      int(cycle.get("intervalMin", 10)) * 60_000)
                    last_ms     = int(cycle.get("lastApplyMs") or 0)
                    if last_ms > 0 and (now_ms - last_ms) < interval_ms:
                        continue
                    pool_name = cycle.get("pool", "all")
                    order     = cycle.get("order", "sequential")
                    next_idx  = int(cycle.get("nextIdx") or 0)
                self._cycle_screen(i, pool_name, order, next_idx, now_ms)
            except Exception as e:
                print(f"[cycle] screen={i} failed: {e}")

    def _cycle_screen(self, screen: int, pool_name: str, order: str,
                      next_idx: int, now_ms: int) -> None:
        lib = library_dir()
        cat_path = lib / "library.json"
        if not cat_path.exists():
            return
        try:
            cat = json.loads(cat_path.read_text(encoding="utf-8"))
        except Exception:
            return
        items = cat.get("items", [])
        if pool_name == "pinned":
            items = [it for it in items if isinstance(it, dict) and it.get("pinned")]
        else:
            items = [it for it in items if isinstance(it, dict) and "file" in it]
        if not items:
            return
        if order == "random":
            # Pick any item except the one currently showing if we can
            # tell from the current bgImage path.
            with self.bridge.config_lock:
                s = self.bridge.config["screens"].get(str(screen), {})
                cur_path = str(s.get("bgImage") or "")
            cur_name = os.path.basename(cur_path)
            choices = [it for it in items if it.get("file") != cur_name] or items
            pick = random.choice(choices)
            chosen_idx = items.index(pick)
        else:
            chosen_idx = next_idx % len(items)
            pick = items[chosen_idx]
        file = pick.get("file")
        if not file:
            return
        fp = lib / file
        if not fp.is_file():
            return
        try:
            data = fp.read_bytes()
        except Exception as e:
            print(f"[cycle] read {fp} failed: {e}")
            return
        # _update_background handles bgImage path + replication to
        # mirrors + the new-config-pushed-to-WS dance.
        ok = self.bridge._update_background(screen, data)
        if not ok:
            return
        # Bookkeeping: record when we fired + advance the sequential
        # pointer. These live inside `cycle` so they're persisted.
        with self.bridge.config_lock:
            s = self.bridge.config.get("screens", {}).get(str(screen))
            if isinstance(s, dict):
                cy = s.setdefault("cycle", {})
                cy["lastApplyMs"] = now_ms
                cy["nextIdx"] = (chosen_idx + 1) % len(items)
                cfg_snapshot = json.loads(json.dumps(self.bridge.config))
        try:
            save_config(cfg_snapshot)
        except Exception as e:
            print(f"[cycle] save_config failed: {e}")
        print(f"[cycle] screen={screen} -> {file} (pool={pool_name}, order={order})")


class HotkeyListener:
    """Win32 global hotkey registration + dispatch. Registers
    Ctrl+Shift+1..4 to fire preset-apply on each screen's matching
    slot — one hotkey activates that slot's snapshot on every
    active screen at once, so the whole desktop's look swaps in a
    single keystroke.

    Implementation: each hotkey lives on this listener thread via
    `RegisterHotKey(NULL, id, MOD_CTRL|MOD_SHIFT, vk)`; the thread
    pumps GetMessage to receive WM_HOTKEY. Stop posts WM_QUIT so the
    blocking GetMessage returns and the loop exits.

    Disabled: Stop() unregisters the hotkeys so other apps can grab
    Ctrl+Shift+1..4 again. Re-enable by Start()ing a fresh listener.
    """

    # Modifier flags from WinUser.h.
    _MOD_SHIFT   = 0x0004
    _MOD_CONTROL = 0x0002
    _WM_HOTKEY   = 0x0312
    _WM_QUIT     = 0x0012

    # (hotkey-id, modifiers, virtual-key, preset-slot).
    _HOTKEYS = [
        (1, _MOD_CONTROL | _MOD_SHIFT, 0x31, 0),  # Ctrl+Shift+1 -> slot 0
        (2, _MOD_CONTROL | _MOD_SHIFT, 0x32, 1),  # Ctrl+Shift+2 -> slot 1
        (3, _MOD_CONTROL | _MOD_SHIFT, 0x33, 2),  # Ctrl+Shift+3 -> slot 2
        (4, _MOD_CONTROL | _MOD_SHIFT, 0x34, 3),  # Ctrl+Shift+4 -> slot 3
    ]

    def __init__(self, bridge_runtime):
        self.bridge   = bridge_runtime
        self._thread: threading.Thread | None = None
        self._tid     = 0
        self._enabled = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._enabled = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="hotkey-listener")
        self._thread.start()

    def stop(self):
        self._enabled = False
        if not self._thread or not self._tid:
            return
        try:
            user32 = ctypes.windll.user32
            # Post WM_QUIT to break the blocking GetMessage in _run.
            user32.PostThreadMessageW(self._tid, self._WM_QUIT, 0, 0)
        except Exception as e:
            print(f"[hotkey] stop post failed: {e}")

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self):
        try:
            user32  = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
        except Exception as e:
            print(f"[hotkey] ctypes unavailable: {e}")
            return
        self._tid = kernel32.GetCurrentThreadId()
        registered: list[int] = []
        for hk_id, mods, vk, _slot in self._HOTKEYS:
            try:
                # `hwnd=None` registers the hotkey for the calling
                # thread; messages arrive in this thread's queue.
                if user32.RegisterHotKey(None, hk_id, mods, vk):
                    registered.append(hk_id)
                else:
                    print(f"[hotkey] register id={hk_id} failed "
                          f"(probably already in use by another app)")
            except Exception as e:
                print(f"[hotkey] register id={hk_id} crashed: {e}")
        if not registered:
            print("[hotkey] no hotkeys registered; listener idle")
            return
        print(f"[hotkey] active — Ctrl+Shift+1..{len(registered)} = preset slot 1..{len(registered)}")
        try:
            from ctypes import wintypes
            msg = wintypes.MSG()
            while self._enabled:
                # GetMessageW returns 0 on WM_QUIT, -1 on error, >0 otherwise.
                bret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if bret <= 0:
                    break
                if msg.message == self._WM_HOTKEY:
                    slot = self._slot_for_id(int(msg.wParam))
                    if slot is not None:
                        self._fire_preset(slot)
        finally:
            for hk_id in registered:
                try: user32.UnregisterHotKey(None, hk_id)
                except Exception: pass
            self._tid = 0

    def _slot_for_id(self, hk_id: int) -> int | None:
        for id_, _mods, _vk, slot in self._HOTKEYS:
            if id_ == hk_id:
                return slot
        return None

    def _fire_preset(self, slot: int) -> None:
        """Apply the matching preset slot on every active screen.
        Mirrors are already skipped by `apply_preset` via
        `_block_if_mirror`, so we don't double-fire there."""
        try:
            count = int(self.bridge._get_screen_count())
        except Exception:
            count = 1
        applied = 0
        for i in range(count):
            try:
                if self.bridge.apply_preset(i, slot) is not None:
                    applied += 1
            except Exception as e:
                print(f"[hotkey] apply_preset screen={i} slot={slot} failed: {e}")
        print(f"[hotkey] slot={slot} applied to {applied}/{count} screen(s)")


class ProfileWatcher:
    """Foreground-window watcher that swaps presets based on which exe
    is currently focused. Rule schema:

        {
          "id":         "p_…",   # unique
          "enabled":    True,
          "exe":        "cyberpunk2077.exe",   # case-insensitive
          "screen":     0,                     # 0..N-1 or None (= all)
          "presetSlot": 1,                     # 0..3
          "label":      "Cyberpunk 2077"       # user-friendly, optional
        }

    Stored under `config.profiles` (list). The watcher polls
    `GetForegroundWindow → QueryFullProcessImageName` every second,
    activates the first matching rule, and snapshots the previous
    per-screen state so deactivation restores it. Only one rule is
    active at a time — when the foreground changes to something else
    matched by a different rule, we revert + activate cleanly.

    Mirrored screens are handled implicitly: `apply_preset` rejects on
    mirrors, so the source's preset apply naturally fans out via
    `_replicate_to_mirrors`.
    """

    POLL_INTERVAL_S = 1.0

    def __init__(self, bridge_runtime):
        self.bridge   = bridge_runtime
        self._stop    = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_rule_id: str | None = None
        # screen -> snapshot dict (full screen settings at activation time).
        # On revert we restore PRESET_SNAPSHOT_KEYS only — the same key
        # set save/apply_preset uses, so we don't drift fields the rule
        # didn't touch.
        self._stash: dict[int, dict] = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="profile-watcher")
        self._thread.start()
        print("[profiles] watcher running (1 Hz)")

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self.POLL_INTERVAL_S):
            try:
                self._tick()
            except Exception as e:
                print(f"[profiles] tick failed: {e}")

    def _tick(self):
        with self.bridge.config_lock:
            raw_rules = list(self.bridge.config.get("profiles", []) or [])
        enabled = [r for r in raw_rules
                   if isinstance(r, dict) and r.get("enabled") and r.get("exe")]
        if not enabled:
            if self._active_rule_id is not None:
                self._revert()
            return
        exe = self._foreground_exe()
        matched = None
        for r in enabled:
            target = str(r.get("exe", "")).strip().lower()
            if target and target == exe:
                matched = r
                break
        if matched is None:
            if self._active_rule_id is not None:
                self._revert()
            return
        rule_id = str(matched.get("id") or "")
        if rule_id == self._active_rule_id:
            return   # already active, nothing to do
        # Different rule → swap. Revert previous first so the stash
        # snapshot reflects the user's manual state, not the prior
        # rule's preset.
        if self._active_rule_id is not None:
            self._revert()
        self._activate(matched)

    def _foreground_exe(self) -> str:
        if not _user32:
            return ""
        try:
            kernel32 = ctypes.windll.kernel32
            hwnd = _user32.GetForegroundWindow()
            if not hwnd:
                return ""
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return ""
            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000 — works on
            # processes the bridge can't fully open (e.g. system
            # processes), which is what we want for foreground check.
            h = kernel32.OpenProcess(0x1000, False, pid.value)
            if not h:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(len(buf))
                if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    return ""
                return os.path.basename(buf.value).lower()
            finally:
                kernel32.CloseHandle(h)
        except Exception:
            return ""

    def _screens_for_rule(self, rule: dict) -> list[int]:
        screen = rule.get("screen")
        count  = int(self.bridge._get_screen_count())
        if screen is None or screen == "" or screen == "all":
            return list(range(count))
        try:
            n = int(screen)
        except (TypeError, ValueError):
            return list(range(count))
        if 0 <= n < count:
            return [n]
        return []

    def _activate(self, rule: dict):
        slot = int(rule.get("presetSlot", 0) or 0)
        if not (0 <= slot < PRESET_SLOTS):
            return
        screens = self._screens_for_rule(rule)
        # Snapshot current state for each target screen BEFORE applying
        # so revert restores precisely what the user had.
        for s in screens:
            try:
                with self.bridge.config_lock:
                    cur = self.bridge.config.get("screens", {}).get(str(s)) or {}
                    self._stash[s] = copy.deepcopy(cur)
            except Exception:
                pass
        applied = 0
        for s in screens:
            if self.bridge.apply_preset(s, slot) is not None:
                applied += 1
        self._active_rule_id = str(rule.get("id") or "")
        label = rule.get("label") or rule.get("exe") or "(rule)"
        print(f"[profiles] activated {label!r} -> slot {slot} on {applied}/{len(screens)} screen(s)")

    def _revert(self):
        if not self._stash:
            self._active_rule_id = None
            return
        # Write back the snapshot's PRESET_SNAPSHOT_KEYS values to each
        # stashed screen + push the new settings.
        for s, stash in list(self._stash.items()):
            try:
                def mutate(cur, _snap=stash):
                    for k in PRESET_SNAPSHOT_KEYS:
                        if k in _snap:
                            cur[k] = copy.deepcopy(_snap[k])
                snap = self.bridge._mutate_screen(s, mutate)
                if snap is not None:
                    self.bridge.push_settings(s, snap)
                    self.bridge._replicate_to_mirrors(s)
            except Exception as e:
                print(f"[profiles] revert screen={s} failed: {e}")
        self._stash.clear()
        prior = self._active_rule_id
        self._active_rule_id = None
        print(f"[profiles] reverted (was {prior!r})")


class UdpReceiver(asyncio.DatagramProtocol):
    """Accepts two wire formats from the SignalRGB plugin:

      • Single-packet  "SR" — original 7-byte header + full RGB payload.
                       Forwarded verbatim. Used when the frame fits in
                       SignalRGB's per-packet UDP cap (≤ 36×36).
      • Chunked        "SC" — 12-byte header carrying frameId/chunkIdx/
                       chunkCount/dims/pixelOffset. Bridge buffers chunks
                       per (screen, frameId) and only forwards once every
                       chunk has arrived. Stale partials (different frameId
                       or older than 200 ms) are evicted lazily as new
                       chunks come in.
    """

    # Partials keyed by (screen, frameId). Each entry tracks dims, expected
    # chunk count, the RGB bytes accumulator, and the per-chunk arrival
    # bitmap so we know when reassembly is complete.
    _STALE_AFTER_S = 0.2

    def __init__(self, broadcaster: Broadcaster, loop: asyncio.AbstractEventLoop):
        self.broadcaster = broadcaster
        self.loop = loop
        self.count = 0
        self.warned_bad = 0
        self.partials: dict[tuple[int, int], dict] = {}
        self._chunk_count = 0

    def datagram_received(self, data: bytes, addr):
        if len(data) < 7 or data[0] != 0x53:
            if self.warned_bad < 3:
                self.warned_bad += 1
                print(f"[udp] malformed datagram from {addr}: len={len(data)} head={data[:8].hex()}")
            return
        magic1 = data[1]
        if magic1 == 0x52:           # 'R' — original single-packet frame
            screen = data[2]
            self.count += 1
            if self.count == 1 or self.count % 600 == 0:
                print(f"[udp] {self.count} single-packet frames "
                      f"(last: screen={screen}, {len(data)} bytes)")
            self.loop.create_task(self.broadcaster.broadcast_frame(screen, data))
            return
        if magic1 == 0x43:           # 'C' — chunked frame
            self._handle_chunked(data, addr)
            return
        if self.warned_bad < 3:
            self.warned_bad += 1
            print(f"[udp] unknown magic from {addr}: head={data[:4].hex()}")

    def _handle_chunked(self, data: bytes, addr):
        if len(data) < 12:
            return
        screen      = data[2]
        frame_id    = data[3]
        chunk_idx   = data[4]
        chunk_count = data[5]
        w = (data[6]  << 8) | data[7]
        h = (data[8]  << 8) | data[9]
        pixel_off = (data[10] << 8) | data[11]
        payload   = data[12:]
        expected_payload_bytes = len(payload)
        if chunk_count == 0 or chunk_idx >= chunk_count:
            return
        if w * h <= 0 or w * h > 1 << 18:        # sanity ceiling (~262 K pixels)
            return
        key = (screen, frame_id)
        part = self.partials.get(key)
        # Different (screen, frameId) → fresh entry. We also evict any other
        # partials for this screen whose frame_id differs and that's older
        # than STALE_AFTER_S: out-of-order packets after a frame switch
        # would otherwise pile up.
        now = self.loop.time()
        if part is None:
            # Allocate the assembled RGB buffer up front
            try:
                part = {
                    "w": w, "h": h,
                    "count": chunk_count,
                    "rgb": bytearray(w * h * 3),
                    "got": [False] * chunk_count,
                    "got_count": 0,
                    "started": now,
                }
            except (MemoryError, OverflowError):
                return
            self.partials[key] = part
            self._evict_stale(now, exclude=key)
        # Sanity: dims must match the partial. If a misbehaving sender
        # changes dims mid-frame we drop the whole partial and start over.
        if part["w"] != w or part["h"] != h or part["count"] != chunk_count:
            del self.partials[key]
            return
        # Bounds-check the payload against the partial's RGB buffer.
        rgb_off = pixel_off * 3
        if rgb_off + expected_payload_bytes > len(part["rgb"]):
            del self.partials[key]
            return
        if part["got"][chunk_idx]:
            return                                # duplicate chunk — ignore
        part["rgb"][rgb_off:rgb_off + expected_payload_bytes] = payload
        part["got"][chunk_idx] = True
        part["got_count"] += 1
        self._chunk_count += 1
        if part["got_count"] >= chunk_count:
            # Reassembled — synthesise an SR frame so downstream code stays
            # unchanged. 7-byte header + the RGB blob we just filled.
            frame = bytearray(7 + len(part["rgb"]))
            frame[0] = 0x53; frame[1] = 0x52
            frame[2] = screen
            frame[3] = (w >> 8) & 0xff; frame[4] = w & 0xff
            frame[5] = (h >> 8) & 0xff; frame[6] = h & 0xff
            frame[7:] = part["rgb"]
            del self.partials[key]
            self.count += 1
            if self.count == 1 or self.count % 600 == 0:
                print(f"[udp] {self.count} chunked frames assembled "
                      f"(last: screen={screen}, {w}x{h}, {chunk_count} chunks)")
            self.loop.create_task(self.broadcaster.broadcast_frame(screen, bytes(frame)))

    def _evict_stale(self, now: float, exclude: tuple[int, int] | None = None):
        for k, p in list(self.partials.items()):
            if k == exclude:
                continue
            if now - p["started"] > self._STALE_AFTER_S:
                del self.partials[k]


# ============================================================================
# Bridge thread — owns the asyncio loop
# ============================================================================

class BridgeRuntime:
    """Lives in a daemon thread, owns the asyncio loop and the broadcaster."""

    def __init__(self, config: dict, config_lock: threading.Lock):
        self.config = config
        self.config_lock = config_lock
        self.loop: asyncio.AbstractEventLoop | None = None
        self.broadcaster: Broadcaster | None = None
        self._ready = threading.Event()
        self._paused = False
        self.fullscreen_watcher = FullscreenWatcher(
            on_state_change=self._on_fullscreen_state,
            is_enabled=self._is_fullscreen_pause_enabled,
        )

    def _get_settings(self, screen: int) -> dict:
        with self.config_lock:
            return dict(self.config["screens"].get(str(screen), DEFAULT_SCREEN_SETTINGS))

    def _get_screen_count(self) -> int:
        with self.config_lock:
            return int(self.config.get("screenCount", 1))

    def _is_paused(self) -> bool:
        return self._paused

    def _is_fullscreen_pause_enabled(self) -> bool:
        with self.config_lock:
            return bool(self.config.get("fullscreenPause", True))

    def _on_fullscreen_state(self, paused: bool):
        # Called from the watcher thread when fullscreen-active flips.
        self._paused = bool(paused)
        if self.broadcaster:
            self.broadcaster.push_pause_threadsafe(self._paused)

    def _update_background(self, screen: int, png_bytes: bytes) -> bool:
        """Persist a builder-uploaded PNG and point the screen's bgImage
        setting at it. Unique-timestamped filename so the wallpaper page
        sees a new URL and refetches (avoids stale-cache hits). Old
        screen-N-*.png files are deleted so the screens/ folder doesn't
        bloat over many edits."""
        if self._block_if_mirror(screen, "background-upload"):
            return False
        try:
            millis = int(time.time() * 1000)
            target = screens_dir() / f"screen-{screen}-{millis}.png"
            target.write_bytes(png_bytes)
            for old in screens_dir().glob(f"screen-{screen}-*.png"):
                if old != target:
                    try: old.unlink()
                    except OSError: pass
            with self.config_lock:
                self.config["screens"][str(screen)]["bgImage"] = str(target)
                cfg_snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(cfg_snapshot)
            except Exception as e:
                print(f"[bg] save_config failed: {e}")
            print(f"[bg] screen={screen} saved {target.name} ({len(png_bytes)} bytes)")
            # Replicate the new bgImage path to every mirroring screen.
            # The PNG file itself is shared (mirrors point at the same
            # screen-N-*.png), so no per-mirror copy is needed.
            self._replicate_to_mirrors(screen)
            return True
        except Exception as e:
            print(f"[bg] update failed: {e}")
            return False

    def push_settings(self, screen: int, settings: dict):
        if self.broadcaster:
            self.broadcaster.push_settings_threadsafe(screen, settings)

    # ── Mirror replication helpers ───────────────────────────────────────
    # Any time a per-screen mutation runs against a screen that has
    # mirrors, the same change has to land on each mirror so the
    # invariant "mirror == source" holds. Single-key changes use the
    # cheaper key path; widget-array / preset / background changes use
    # the full snapshot path because the mutation isn't a single
    # key-value pair.

    def _block_if_mirror(self, screen: int, what: str) -> bool:
        if self._is_mirror(screen):
            print(f"[mirror] screen {screen} is a mirror; ignoring {what}")
            return True
        return False

    def _replicate_to_mirrors(self, source: int) -> None:
        """Copy every mirrorable key from `source` into each screen
        mirroring it, then push the new settings to those mirrors' WS
        clients. Used after widget-array mutations and background
        uploads where a single-key replicate isn't enough."""
        mirrors = self._get_mirrors_of(source)
        if not mirrors:
            return
        with self.config_lock:
            src = self.config.get("screens", {}).get(str(source))
            if not isinstance(src, dict):
                return
            src_copy = json.loads(json.dumps(src))
        for m in mirrors:
            def mutate(s, sc=src_copy):
                for k, v in sc.items():
                    if k in _NON_MIRRORED_KEYS:
                        continue
                    s[k] = v
            snap = self._mutate_screen(m, mutate)
            if snap is not None:
                self.push_settings(m, snap)

    # ── Widget CRUD ──────────────────────────────────────────────────────
    # All four entry points share the same shape: mutate the in-memory
    # config under config_lock, write it to disk, then push the fresh
    # settings to every WS client on the affected screen so the wallpaper
    # page re-renders. Tray controls and wallpaper-page drag both flow
    # through these.

    def _mutate_screen(self, screen: int, mutator) -> dict | None:
        """Apply `mutator(screen_dict)` under lock, persist, return a snapshot
        of the new screen settings. Returns None if the screen index is bad."""
        with self.config_lock:
            screens = self.config.get("screens", {})
            s = screens.get(str(screen))
            if s is None:
                return None
            mutator(s)
            snapshot   = json.loads(json.dumps(s))
            full_snap  = json.loads(json.dumps(self.config))
        try:
            save_config(full_snap)
        except Exception as e:
            print(f"[widgets] save_config failed: {e}")
        return snapshot

    def add_widget(self, screen: int, widget_type: str, x: int | None = None, y: int | None = None) -> dict | None:
        if widget_type not in WIDGET_DEFAULTS:
            print(f"[widgets] unknown type: {widget_type!r}")
            return None
        if self._block_if_mirror(screen, "widget-add"): return None
        defaults = WIDGET_DEFAULTS[widget_type]

        def mutate(s):
            existing = s.setdefault("widgets", [])
            # Compose a new id deterministic-ish from current count + ms time
            # so two rapid clicks don't collide.
            new_id = f"w_{int(time.time() * 1000) % 10_000_000}_{len(existing)}"
            entry = {
                "id":      new_id,
                "type":    widget_type,
                "x":       defaults["x"] if x is None else int(x),
                "y":       defaults["y"] if y is None else int(y),
                "w":       defaults["w"],
                "h":       defaults["h"],
                "options": dict(defaults["options"]),
            }
            existing.append(entry)
            # Adding a widget also implicitly puts the page in edit mode —
            # otherwise the user can't find/move the freshly-added one.
            s["widgetsLocked"] = False

        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
        return snap

    def remove_widget(self, screen: int, widget_id: str) -> dict | None:
        if self._block_if_mirror(screen, "widget-remove"): return None
        def mutate(s):
            s["widgets"] = [w for w in s.get("widgets", []) if w.get("id") != widget_id]
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
        return snap

    def update_widget(self, screen: int, widget_id: str, fields: dict) -> dict | None:
        if self._block_if_mirror(screen, "widget-update"): return None
        # Whitelist mutable fields — never let a wallpaper-page bug bleed
        # arbitrary keys into our config file.
        allowed = {"x", "y", "w", "h", "options"}
        def mutate(s):
            for entry in s.get("widgets", []):
                if entry.get("id") != widget_id:
                    continue
                for k in allowed:
                    if k not in fields:
                        continue
                    if k == "options" and isinstance(fields[k], dict):
                        entry.setdefault("options", {}).update(fields[k])
                    else:
                        entry[k] = fields[k]
                break
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
        return snap

    # ----- Preset slots -----

    def save_preset(self, screen: int, slot: int) -> dict | None:
        """Capture the screen's current state into preset slot `slot`.
        The snapshot is a deep copy of every PRESET_SNAPSHOT_KEYS value,
        so later mutations to the live settings don't drift into the
        saved slot."""
        if not (0 <= slot < PRESET_SLOTS):
            print(f"[preset] bad slot: {slot}")
            return None
        def mutate(s):
            snapshot = {k: copy.deepcopy(s.get(k, DEFAULT_SCREEN_SETTINGS.get(k)))
                        for k in PRESET_SNAPSHOT_KEYS}
            presets = list(s.get("presets") or [None] * PRESET_SLOTS)
            while len(presets) < PRESET_SLOTS:
                presets.append(None)
            presets[slot] = snapshot
            s["presets"] = presets
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            print(f"[preset] saved screen={screen} slot={slot}")
        return snap

    def apply_preset(self, screen: int, slot: int) -> dict | None:
        """Write a saved snapshot back into the screen's live settings.
        Whitelist the keys so a malformed slot can't sneak unexpected
        fields into the config."""
        if not (0 <= slot < PRESET_SLOTS):
            print(f"[preset] bad slot: {slot}")
            return None
        if self._block_if_mirror(screen, "preset-apply"): return None
        with self.config_lock:
            screen_cfg = self.config.get("screens", {}).get(str(screen))
            if not screen_cfg:
                return None
            presets = screen_cfg.get("presets") or []
            if slot >= len(presets) or presets[slot] is None:
                print(f"[preset] empty slot: screen={screen} slot={slot}")
                return None
            snapshot = copy.deepcopy(presets[slot])
        def mutate(s):
            for k in PRESET_SNAPSHOT_KEYS:
                if k in snapshot:
                    s[k] = snapshot[k]
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
            print(f"[preset] applied screen={screen} slot={slot}")
        return snap

    def clear_preset(self, screen: int, slot: int) -> dict | None:
        if not (0 <= slot < PRESET_SLOTS):
            return None
        def mutate(s):
            presets = list(s.get("presets") or [None] * PRESET_SLOTS)
            while len(presets) < PRESET_SLOTS:
                presets.append(None)
            presets[slot] = None
            s["presets"] = presets
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            print(f"[preset] cleared screen={screen} slot={slot}")
        return snap

    def set_widgets_locked(self, screen: int, locked: bool) -> dict | None:
        if self._block_if_mirror(screen, "widgets-lock"): return None
        def mutate(s):
            s["widgetsLocked"] = bool(locked)
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
        return snap

    # ── Profile rules CRUD ───────────────────────────────────────────────
    def _persist_profiles(self):
        """Save config + push every screen's current settings so any
        connected Configurator tab sees the new profile list (profiles
        ride in the settings payload as a top-level field)."""
        with self.config_lock:
            snapshot = json.loads(json.dumps(self.config))
        try:
            save_config(snapshot)
        except Exception as e:
            print(f"[profiles] save_config failed: {e}")
        # Re-push settings to every active screen so the Configurator
        # picks up the new profiles list on its current WS frame.
        for i in range(N_SCREENS):
            try:
                self.push_settings(i, snapshot["screens"][str(i)])
            except Exception:
                pass

    def add_profile(self, exe: str, label: str | None,
                    screen, preset_slot: int) -> dict | None:
        exe = (exe or "").strip().lower()
        if not exe:
            return None
        try:
            preset_slot = int(preset_slot)
        except (TypeError, ValueError):
            return None
        if not (0 <= preset_slot < PRESET_SLOTS):
            return None
        # Normalise screen target: None / "all" → null (= all screens),
        # otherwise integer 0..N-1.
        if screen in (None, "", "all"):
            screen_val = None
        else:
            try:
                n = int(screen)
                screen_val = n if 0 <= n < N_SCREENS else None
            except (TypeError, ValueError):
                screen_val = None
        rid = f"p_{int(time.time() * 1000) % 10_000_000}"
        rule = {
            "id":         rid,
            "enabled":    True,
            "exe":        exe,
            "label":      (label or "").strip() or exe,
            "screen":     screen_val,
            "presetSlot": preset_slot,
        }
        with self.config_lock:
            self.config.setdefault("profiles", []).append(rule)
        self._persist_profiles()
        return rule

    def update_profile(self, rid: str, fields: dict) -> dict | None:
        allowed = {"enabled", "exe", "label", "screen", "presetSlot"}
        target = None
        with self.config_lock:
            for r in self.config.get("profiles", []):
                if r.get("id") == rid:
                    target = r
                    break
            if target is None:
                return None
            for k, v in fields.items():
                if k not in allowed:
                    continue
                if k == "enabled":
                    target["enabled"] = bool(v)
                elif k == "exe":
                    target["exe"] = str(v or "").strip().lower()
                elif k == "label":
                    target["label"] = str(v or "").strip()
                elif k == "screen":
                    if v in (None, "", "all"):
                        target["screen"] = None
                    else:
                        try:
                            n = int(v)
                            target["screen"] = n if 0 <= n < N_SCREENS else None
                        except (TypeError, ValueError):
                            target["screen"] = None
                elif k == "presetSlot":
                    try:
                        n = int(v)
                        if 0 <= n < PRESET_SLOTS:
                            target["presetSlot"] = n
                    except (TypeError, ValueError):
                        pass
            updated = json.loads(json.dumps(target))
        self._persist_profiles()
        return updated

    def remove_profile(self, rid: str) -> bool:
        with self.config_lock:
            before = list(self.config.get("profiles", []))
            after = [r for r in before if r.get("id") != rid]
            if len(after) == len(before):
                return False
            self.config["profiles"] = after
        # If the removed rule was the currently-active one, ProfileWatcher's
        # next tick (empty match) will revert on its own.
        self._persist_profiles()
        return True

    # ── Backup + Restore ─────────────────────────────────────────────────
    def build_backup_zip(self) -> bytes:
        """Serialise every piece of user state worth re-installing into a
        single ZIP. Three roots:
          • `config.json` at the archive root
          • `library/*` — wallpapers + thumbs + library.json
          • `screens/*` — builder-uploaded backgrounds, one per screen
        Anything else under %LOCALAPPDATA%\\SignalRGBWallpaper is
        regenerated on demand and isn't worth carrying around."""
        import io, zipfile
        buf = io.BytesIO()
        with self.config_lock:
            cfg_snapshot = json.dumps(self.config, indent=2).encode("utf-8")
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("config.json", cfg_snapshot)
            lib = library_dir()
            if lib.exists():
                for p in lib.rglob("*"):
                    if p.is_file():
                        z.write(p, "library/" + p.relative_to(lib).as_posix())
            scr = screens_dir()
            if scr.exists():
                for p in scr.rglob("*"):
                    if p.is_file():
                        z.write(p, "screens/" + p.relative_to(scr).as_posix())
        return buf.getvalue()

    def restore_backup_zip(self, data: bytes) -> dict:
        """Replace the live config + library + screens contents from a
        previously-exported ZIP. Returns a small report dict so the
        caller can surface counts. Destructive: existing library and
        screens files NOT in the ZIP are kept (additive merge for files,
        full replace for config.json) — safer than nuking the folder
        when the user accidentally restores an old backup."""
        import io, zipfile
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise ValueError(f"not a zip: {e}")
        if "config.json" not in zf.namelist():
            raise ValueError("backup is missing config.json")

        # Validate config.json parses + has the version field we expect.
        with zf.open("config.json") as f:
            cfg_text = f.read().decode("utf-8")
        try:
            new_cfg = json.loads(cfg_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"config.json is not valid JSON: {e}")
        if not isinstance(new_cfg, dict) or "screens" not in new_cfg:
            raise ValueError("config.json is missing required keys")

        # Extract library/* and screens/* into their respective dirs.
        # Path-traversal guard: refuse anything that resolves outside
        # the target folder.
        lib_root = library_dir().resolve()
        scr_root = screens_dir().resolve()
        copied = {"library": 0, "screens": 0}
        for name in zf.namelist():
            if name in ("", "config.json") or name.endswith("/"):
                continue
            parts = name.split("/", 1)
            if len(parts) != 2:
                continue
            head, rel = parts
            if head == "library":
                target = (lib_root / rel).resolve()
                if not str(target).startswith(str(lib_root)):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                copied["library"] += 1
            elif head == "screens":
                target = (scr_root / rel).resolve()
                if not str(target).startswith(str(scr_root)):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                copied["screens"] += 1

        # Swap the live config in place. Persist + push to all clients.
        with self.config_lock:
            self.config.clear()
            self.config.update(new_cfg)
            snapshot = json.loads(json.dumps(self.config))
        try:
            save_config(snapshot)
        except Exception as e:
            print(f"[restore] save_config failed: {e}")
        # Rebuild library.json from the now-restored disk contents so
        # any catalogue drift gets fixed.
        try:
            _library_rebuild_catalogue(library_dir())
        except Exception as e:
            print(f"[restore] library rebuild failed: {e}")
        # Push every screen's new settings to connected wallpaper pages.
        for i in range(N_SCREENS):
            s = snapshot.get("screens", {}).get(str(i))
            if isinstance(s, dict):
                self.push_settings(i, s)
        return copied

    def get_health_status(self) -> dict:
        """Snapshot of "is the install actually working?" signals for
        the tray's System-status dialog. Cheap to compute — meant to
        be called on-demand from the dialog open path."""
        # SignalRGB plugin file. Windows redirects the Documents folder
        # to OneDrive on a lot of installs, so `Path.home() / "Documents"`
        # is *not* where Inno Setup's {userdocs} actually put the
        # plugin. Walk a list of candidate roots (registry Personal,
        # OneDrive paths, plain Documents) and pick the first one that
        # has the file — fall back to the registry-preferred path for
        # the "Open plugins folder" button when nothing matches.
        plugin_rel = Path("WhirlwindFX") / "Plugins" / "SignalRGB_Desktop_Wallpaper.js"
        candidate_roots = _candidate_documents_dirs()
        plugin_path = None
        for root in candidate_roots:
            fp = root / plugin_rel
            if fp.is_file():
                plugin_path = fp
                break
        if plugin_path is None and candidate_roots:
            plugin_path = candidate_roots[0] / plugin_rel
        plugin_present = bool(plugin_path and plugin_path.is_file())

        # SignalRGB.exe / SignalRgb / SignalRGBLauncher running.
        signalrgb_running = False
        try:
            for p in psutil.process_iter(["name"]):
                n = (p.info.get("name") or "").lower()
                if "signalrgb" in n:
                    signalrgb_running = True
                    break
        except Exception:
            pass

        # Wallpaper pages connected via WS (one per active monitor).
        # `client_roles` distinguishes the Configurator's own WS from
        # actual wallpaper pages — without it, the user sees their own
        # open Configurator tab counted, which is misleading.
        pages_connected = 0
        if self.broadcaster:
            try:
                roles = getattr(self.broadcaster, "client_roles", {}) or {}
                if roles:
                    pages_connected = sum(
                        1 for r in roles.values() if r == "wallpaper")
                else:
                    pages_connected = sum(
                        len(s) for s in self.broadcaster.clients_by_screen.values())
            except Exception:
                pass

        # LHM only matters if at least one Hardware Sensor widget exists.
        lhm_widget_present = False
        with self.config_lock:
            for s in self.config.get("screens", {}).values():
                if not isinstance(s, dict):
                    continue
                for w in s.get("widgets", []):
                    if isinstance(w, dict) and w.get("type") == "hardware-sensor":
                        lhm_widget_present = True
                        break
                if lhm_widget_present:
                    break
        lhm_online = False
        lhm_count = 0
        if self.hwmon is not None:
            try:
                snap = self.hwmon.get_snapshot()
                if isinstance(snap, dict):
                    lhm_count = len(snap)
                    lhm_online = lhm_count > 0
            except Exception:
                pass

        return {
            "plugin_present":    plugin_present,
            "plugin_path":       str(plugin_path) if plugin_path else "",
            "plugin_dir":        str(plugin_path.parent) if plugin_path else "",
            "signalrgb_running": signalrgb_running,
            "pages_connected":   pages_connected,
            "lhm_widget_present": lhm_widget_present,
            "lhm_online":        lhm_online,
            "lhm_count":         lhm_count,
        }

    def reset_screen(self, screen: int) -> dict | None:
        """Reset every mirrorable setting on this screen back to its
        DEFAULT_SCREEN_SETTINGS value. Per-screen physical attributes
        (viewport, mirrorOf, presets) are preserved — the user's
        monitor identity and saved snapshots aren't lost when they
        ask for a clean slate."""
        if self._block_if_mirror(screen, "reset-screen"): return None
        def mutate(s):
            for k, v in DEFAULT_SCREEN_SETTINGS.items():
                if k in _NON_MIRRORED_KEYS:
                    continue
                # Deep-copy mutable defaults so a later mutation doesn't
                # bleed into the global DEFAULT_SCREEN_SETTINGS template.
                s[k] = copy.deepcopy(v)
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
            print(f"[reset] screen={screen} restored to defaults")
        return snap

    # Keys the wallpaper page / configurator are allowed to set via the
    # generic `setting-update` WS command. Whitelisted so a buggy page
    # can't write arbitrary garbage into config.json — anything not on
    # this list is silently dropped (with a console warning).
    _SETTABLE_SCREEN_KEYS = {
        "bgImage", "bgImageUrl", "bgFit", "bgDim",
        "barLayout", "showBars", "glowStrength",
        "gridBlur", "stripesBlur", "barHeight", "barWidth",
        "showStatus",
        "ambientEffect", "ambientTint", "ambientDensity",
        "pixelfx", "parallax3d",
        "audioGlow", "audioGlowIntensity", "audioGlowTint",
        "widgetsLocked",
        # Mirror toggle — special-cased in update_screen_setting below
        # because activation copies the source's state onto self.
        "mirrorOf",
        # Auto-cycle settings — partial-merge in _update_cycle below so
        # the configurator can send just `enabled` or `intervalMin`
        # without resetting `lastApplyMs`/`nextIdx`.
        "cycle",
    }

    def _get_mirrors_of(self, source: int) -> list[int]:
        """Return every screen index whose `mirrorOf` currently points
        at `source`. Read-only — used by the propagation paths to know
        where to fan a settings change out to."""
        out = []
        with self.config_lock:
            screens = self.config.get("screens", {})
            for k, s in screens.items():
                try:
                    idx = int(k)
                except ValueError:
                    continue
                if idx == source:
                    continue
                if isinstance(s, dict) and s.get("mirrorOf") == source:
                    out.append(idx)
        return out

    def _is_mirror(self, screen: int) -> bool:
        with self.config_lock:
            s = self.config.get("screens", {}).get(str(screen))
            return bool(isinstance(s, dict) and s.get("mirrorOf") is not None)

    def update_screen_setting(self, screen: int, key: str, value) -> dict | None:
        if key not in self._SETTABLE_SCREEN_KEYS:
            print(f"[settings] ignoring non-whitelisted key: {key!r}")
            return None
        # Mirror toggle has its own path: validate target, copy snapshot,
        # and don't replicate the toggle itself to other screens.
        if key == "mirrorOf":
            return self._set_mirror_of(screen, value)
        # Cycle is a partial-merge to preserve scheduler bookkeeping
        # (lastApplyMs / nextIdx) across config changes.
        if key == "cycle":
            return self._update_cycle(screen, value)
        # Mutations on a mirror are rejected at the bridge as a safety net
        # — the Configurator already disables UI controls, but a stale
        # tab or a future REST client mustn't be able to drift a mirror
        # away from its source.
        if self._is_mirror(screen):
            print(f"[settings] screen {screen} is a mirror; ignoring {key!r}")
            return None
        def mutate(s):
            s[key] = value
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            if key not in _NON_MIRRORED_KEYS:
                for m in self._get_mirrors_of(screen):
                    msnap = self._mutate_screen(m, lambda s, k=key, v=value: s.__setitem__(k, v))
                    if msnap is not None:
                        self.push_settings(m, msnap)
        return snap

    def _set_mirror_of(self, screen: int, value) -> dict | None:
        """Activate / deactivate Mirror mode on `screen`. Validates the
        target index (no self-mirror, no mirroring an existing mirror),
        then on activation copies every mirrorable key from the source
        into self before flipping the flag."""
        # null / None → deactivate. Just clear the flag; leave the
        # current snapshot in place so the user can resume editing
        # whatever the mirror left behind.
        if value is None or value == "" or value is False:
            def deactivate(s):
                s["mirrorOf"] = None
            snap = self._mutate_screen(screen, deactivate)
            if snap is not None:
                self.push_settings(screen, snap)
            return snap
        try:
            tgt = int(value)
        except (TypeError, ValueError):
            print(f"[mirror] bad target: {value!r}")
            return None
        if not (0 <= tgt < N_SCREENS):
            print(f"[mirror] target {tgt} out of range")
            return None
        if tgt == screen:
            print(f"[mirror] refusing self-mirror on screen {screen}")
            return None
        # Chained mirrors get messy fast (A mirrors B which mirrors C).
        # Reject the inner step so the user has to break the chain first.
        if self._is_mirror(tgt):
            print(f"[mirror] refusing to mirror screen {tgt} (already a mirror)")
            return None
        # Snapshot the source's settable state, then overwrite self with
        # it (minus the per-screen-private keys) and flip the flag.
        with self.config_lock:
            src = self.config.get("screens", {}).get(str(tgt))
            if not isinstance(src, dict):
                return None
            src_copy = json.loads(json.dumps(src))
        def activate(s):
            for k, v in src_copy.items():
                if k in _NON_MIRRORED_KEYS:
                    continue
                s[k] = v
            s["mirrorOf"] = tgt
        snap = self._mutate_screen(screen, activate)
        if snap is not None:
            self.push_settings(screen, snap)
        return snap

    _CYCLE_USER_FIELDS = ("enabled", "intervalMin", "pool", "order")
    _CYCLE_ALLOWED_POOLS  = {"all", "pinned"}
    _CYCLE_ALLOWED_ORDERS = {"sequential", "random"}

    def _update_cycle(self, screen: int, value) -> dict | None:
        """Merge a partial cycle dict into the current settings without
        clobbering the scheduler's own bookkeeping (lastApplyMs,
        nextIdx). Validates pool / order against whitelists so a
        misbehaving client can't write garbage. When the user flips
        enabled on, we reset lastApplyMs to 0 so the very first cycle
        tick triggers immediately rather than waiting a full interval."""
        if not isinstance(value, dict):
            return None
        def mutate(s):
            cur = s.get("cycle") or {}
            if not isinstance(cur, dict):
                cur = {}
            # Start from a fresh deep-copy of defaults to handle older
            # configs that never had cycle at all.
            base = copy.deepcopy(DEFAULT_SCREEN_SETTINGS["cycle"])
            base.update(cur)
            # Only merge user-settable fields; reject anything else.
            was_enabled = bool(base.get("enabled", False))
            for k in self._CYCLE_USER_FIELDS:
                if k not in value:
                    continue
                v = value[k]
                if k == "enabled":
                    base["enabled"] = bool(v)
                elif k == "intervalMin":
                    try:
                        base["intervalMin"] = max(1, min(720, int(v)))
                    except (TypeError, ValueError):
                        pass
                elif k == "pool":
                    if isinstance(v, str) and v in self._CYCLE_ALLOWED_POOLS:
                        base["pool"] = v
                elif k == "order":
                    if isinstance(v, str) and v in self._CYCLE_ALLOWED_ORDERS:
                        base["order"] = v
            # If the user just turned cycling on, kick the first tick
            # immediately by zeroing lastApplyMs.
            if base["enabled"] and not was_enabled:
                base["lastApplyMs"] = 0
            s["cycle"] = base
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
        return snap

    # Whitelist of global (bridge-scoped) keys the Configurator may set via
    # the `bridge-setting-update` WS command. Per-screen keys go through
    # `update_screen_setting` above; this is the global counterpart.
    _SETTABLE_BRIDGE_KEYS = {"screenCount", "presetHotkeysEnabled"}

    def update_bridge_setting(self, key: str, value):
        """Mutate a top-level (non-per-screen) config field. Currently
        screenCount + presetHotkeysEnabled — the Configurator + tray
        use this to retire the legacy Tk dialog as the sole source
        of those knobs.

        Re-pushes every screen's settings so the live screenCount field
        in the settings payload propagates to all connected pages
        (and the Configurator's screen-count input stays in sync if
        multiple Configurator tabs are open)."""
        if key not in self._SETTABLE_BRIDGE_KEYS:
            print(f"[settings] ignoring non-whitelisted bridge key: {key!r}")
            return
        if key == "screenCount":
            try:
                n = max(1, min(N_SCREENS, int(value)))
            except (TypeError, ValueError):
                print(f"[settings] screenCount value not an int: {value!r}")
                return
            with self.config_lock:
                if self.config.get("screenCount") == n:
                    return
                self.config["screenCount"] = n
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            for s in range(N_SCREENS):
                try:
                    self.push_settings(s, snapshot["screens"][str(s)])
                except Exception as e:
                    print(f"[settings] push after screenCount failed: {e}")
            print(f"[settings] screenCount -> {n}")
        elif key == "presetHotkeysEnabled":
            enabled = bool(value)
            with self.config_lock:
                if bool(self.config.get("presetHotkeysEnabled", False)) == enabled:
                    return
                self.config["presetHotkeysEnabled"] = enabled
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            # Spin the listener up or down to match. New listener
            # instance after a stop so the daemon thread can fully
            # terminate before we re-register the hotkeys.
            if enabled:
                if not self.hotkey_listener.is_running():
                    self.hotkey_listener.start()
            else:
                self.hotkey_listener.stop()
                self.hotkey_listener = HotkeyListener(self)
            print(f"[settings] presetHotkeysEnabled -> {enabled}")

    def _on_widget_command(self, screen: int, msg: dict):
        """Asyncio-thread callback bridging Broadcaster→BridgeRuntime. We
        defer the actual persistence + rebroadcast to a thread so the WS
        read loop never blocks on the config-file write."""
        def run():
            t = msg.get("type")
            if   t == "widget-update":
                fields = {k: msg[k] for k in ("x", "y", "w", "h", "options") if k in msg}
                self.update_widget(screen, str(msg.get("id", "")), fields)
            elif t == "widget-add":
                self.add_widget(screen, str(msg.get("widgetType", "")))
            elif t == "widget-remove":
                self.remove_widget(screen, str(msg.get("id", "")))
            elif t == "widgets-lock":
                self.set_widgets_locked(screen, bool(msg.get("locked", True)))
            elif t == "setting-update":
                self.update_screen_setting(screen, str(msg.get("key", "")),
                                           msg.get("value"))
            elif t == "bridge-setting-update":
                self.update_bridge_setting(str(msg.get("key", "")),
                                           msg.get("value"))
            elif t == "viewport":
                self.update_viewport(screen, msg.get("w"), msg.get("h"))
            elif t == "preset-save":
                self.save_preset(screen, int(msg.get("slot", -1)))
            elif t == "preset-apply":
                self.apply_preset(screen, int(msg.get("slot", -1)))
            elif t == "preset-clear":
                self.clear_preset(screen, int(msg.get("slot", -1)))
            elif t == "screen-reset":
                self.reset_screen(screen)
            elif t == "profile-add":
                self.add_profile(
                    exe        = str(msg.get("exe", "")),
                    label      = msg.get("label"),
                    screen     = msg.get("screen"),
                    preset_slot= int(msg.get("presetSlot", 0)))
            elif t == "profile-update":
                rid = str(msg.get("id", ""))
                if rid:
                    fields = {k: msg[k] for k in
                              ("enabled", "exe", "label", "screen", "presetSlot")
                              if k in msg}
                    self.update_profile(rid, fields)
            elif t == "profile-remove":
                rid = str(msg.get("id", ""))
                if rid:
                    self.remove_profile(rid)
        threading.Thread(target=run, daemon=True, name="widget-mutate").start()

    def update_viewport(self, screen: int, w, h) -> dict | None:
        """Stash the wallpaper page's actual viewport size so the configurator
        can scale its layout preview to the real monitor. Skipped silently
        when the size already matches the persisted value so a stable
        connection doesn't write the config file every reconnect."""
        try:
            w = int(w)
            h = int(h)
        except (TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        with self.config_lock:
            s = self.config["screens"].get(str(screen))
            if s is None:
                return None
            if s.get("viewportW") == w and s.get("viewportH") == h:
                return None
        def mutate(s):
            s["viewportW"] = w
            s["viewportH"] = h
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            print(f"[viewport] screen={screen} {w}x{h}")
        return snap

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="bridge-asyncio").start()
        self._ready.wait()
        # Watcher runs on its own daemon thread; needs the asyncio loop
        # ready first so push_pause_threadsafe has a target.
        self.fullscreen_watcher.start()

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.broadcaster = Broadcaster(
            loop,
            self._get_settings,
            self._get_screen_count,
            self._update_background,
            self._is_paused,
            self._on_widget_command,
        )
        # System-stats poller pushes 1 Hz snapshots over the WS once the
        # broadcaster is up. No-op if psutil wasn't bundled into this build.
        # The HwMon poller starts even when LHM isn't running — it'll just
        # report `online: false` until the user starts LibreHardwareMonitor
        # with its Remote Web Server enabled.
        self.hwmon = HwMonPoller()
        self.hwmon.start()
        # Let the broadcaster's /hwmon/sensors HTTP handler reach the
        # poller's snapshot + status. Set here rather than via __init__
        # so the broadcaster doesn't need to know about hwmon at all if
        # the user is on a build without it.
        self.broadcaster.hwmon_provider = self.hwmon
        # Expose the runtime so /backup and /restore HTTP handlers can
        # call back into config + persistence without needing the
        # methods passed individually through the constructor.
        self.broadcaster.bridge_runtime = self
        # Wallpaper-shuffle poller — wakes every 30 s and cycles each
        # screen whose `cycle.enabled` is true past its `intervalMin`.
        self.cycle_scheduler = CycleScheduler(self)
        self.cycle_scheduler.start()
        # Global Ctrl+Shift+1..4 → apply preset slot N on every screen.
        # Off by default; tray toggle flips it on. Stays in this attr
        # even when disabled so the toggle path is symmetrical.
        self.hotkey_listener = HotkeyListener(self)
        with self.config_lock:
            if bool(self.config.get("presetHotkeysEnabled", False)):
                self.hotkey_listener.start()
        # Per-app / per-game profiles — foreground-window watcher.
        # Runs unconditionally; the cost is one syscall per second and
        # the rules list defaults to empty so it's a no-op until the
        # user adds some.
        self.profile_watcher = ProfileWatcher(self)
        self.profile_watcher.start()
        # Windows SMTC poller — drains the "now playing" media session
        # so the now-playing widget can render whatever the user has
        # active (Spotify, Groove, browser HTML5 audio, etc.). No-op
        # when the winrt-Windows.Media.Control package isn't bundled.
        self.nowplaying = NowPlayingPoller()
        self.nowplaying.start()
        self.sysstats = SysStatsPoller(self.broadcaster,
                                       hwmon=self.hwmon,
                                       nowplaying=self.nowplaying)
        self.sysstats.start()
        try:
            loop.run_until_complete(self._serve())
        except Exception as e:
            print(f"[bridge] crashed: {e}")
        finally:
            loop.close()

    async def _serve(self):
        ws_server = await asyncio.start_server(self.broadcaster.handle_client, WS_HOST, WS_PORT)
        await self.loop.create_datagram_endpoint(
            lambda: UdpReceiver(self.broadcaster, self.loop),
            local_addr=(UDP_HOST, UDP_PORT),
        )
        print("SignalRGB Wallpaper bridge — multi-screen + tray")
        print(f"  UDP listener: udp://{UDP_HOST}:{UDP_PORT}  (plugin -> bridge)")
        print(f"  WS server:    ws://{WS_HOST}:{WS_PORT}/?screen=N")
        print(f"  HTTP images:  http://{WS_HOST}:{WS_PORT}/image?path=<absolute path>")
        print(f"  Config:       {config_path()}")
        self._ready.set()
        async with ws_server:
            await ws_server.serve_forever()


# ============================================================================
# Tkinter settings dialog
# ============================================================================

class SettingsDialog:
    """
    Modal-ish per-screen settings window. Built per invocation so we don't
    have to deal with re-showing a destroyed Tk root. Runs on whatever
    thread spawned it — we spawn it on a dedicated daemon thread so the
    pystray tray remains responsive.
    """

    def __init__(self, config: dict, on_save):
        self.config = config            # full config dict (we mutate in-place)
        self.on_save = on_save          # callback(updated_full_config: dict)
        self.root: tk.Tk | None = None
        # Per-screen tk Vars so we can read them back on Save.
        self.vars: list[dict[str, tk.Variable]] = []
        # Top-level (non-per-screen) Vars — currently just screenCount.
        self.global_vars: dict[str, tk.Variable] = {}
        # "Saved at HH:MM:SS" status label — updated on every Save click so
        # iterative tweaks (multi-screen tuning, image picker) have feedback
        # that the persist + push actually happened.
        self._saved_label: tk.Label | None = None

    def show(self):
        self.root = tk.Tk()
        self.root.title("SignalRGB Wallpaper — Settings")
        self.root.geometry("740x720")
        self.root.minsize(620, 540)

        # ── STICKY BOTTOM BUTTON BAR ───────────────────────────────────────
        # Packed FIRST with side="bottom" so it stays anchored even when the
        # notebook above scrolls or the window is resized small. Previous
        # layout could push the buttons off-screen on shorter windows.
        btn_bar = ttk.Frame(self.root)
        btn_bar.pack(side="bottom", fill="x", padx=12, pady=10)
        ttk.Button(btn_bar, text="Close", command=self._on_close).pack(side="right")
        ttk.Button(btn_bar, text="Save",  command=self._on_save).pack(side="right", padx=(0, 8))
        self._saved_label = ttk.Label(btn_bar, text="", foreground="#2a8a2a")
        self._saved_label.pack(side="left")

        # ── GLOBAL: SignalRGB device count ────────────────────────────────
        global_frame = ttk.LabelFrame(self.root, text="SignalRGB device count")
        global_frame.pack(fill="x", padx=12, pady=(12, 4))
        row1 = ttk.Frame(global_frame)
        row1.pack(fill="x", padx=10, pady=(10, 2))
        ttk.Label(row1, text="Number of screens:",
                  font=("Segoe UI", 9, "bold")).pack(side="left")
        sc_var = tk.IntVar(value=int(self.config.get("screenCount", 1)))
        self.global_vars["screenCount"] = sc_var
        ttk.Combobox(row1, textvariable=sc_var, values=[1, 2, 3],
                     state="readonly", width=4).pack(side="left", padx=(8, 0))
        ttk.Label(
            global_frame,
            text="How many virtual 'Desktop Wallpaper' devices SignalRGB exposes. "
                 "Each gets its own canvas slot in SignalRGB's Layouts view, so "
                 "different monitors can be driven with different colours pulled "
                 "from one SignalRGB effect.",
            foreground="#666", font=("Segoe UI", 9), wraplength=680, justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 10))

        # ── GLOBAL: Auto-pause ────────────────────────────────────────────
        autopause_frame = ttk.LabelFrame(self.root, text="Auto-pause")
        autopause_frame.pack(fill="x", padx=12, pady=(0, 4))
        fs_var = tk.BooleanVar(value=bool(self.config.get("fullscreenPause", True)))
        self.global_vars["fullscreenPause"] = fs_var
        ttk.Checkbutton(
            autopause_frame,
            text="Pause glow when a fullscreen application is active",
            variable=fs_var,
        ).pack(anchor="w", padx=10, pady=(10, 0))
        ttk.Label(
            autopause_frame,
            text="Detects fullscreen games, video players, and RDP sessions. "
                 "The glow freezes on its last drawn colours, CPU is saved, and "
                 "playback resumes within ~1 second when you leave fullscreen.",
            foreground="#666", font=("Segoe UI", 9), wraplength=680, justify="left",
        ).pack(anchor="w", padx=30, pady=(0, 10))

        # ── PER-SCREEN NOTEBOOK (each tab is independently scrollable) ───
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        for n in range(N_SCREENS):
            tab = ttk.Frame(notebook)
            notebook.add(tab, text=f"Screen {n+1}")
            scrollable = self._make_scrollable(tab)
            self.vars.append(self._build_tab(scrollable, n))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # -- helpers -----------------------------------------------------------

    def _make_scrollable(self, parent: ttk.Frame) -> ttk.Frame:
        """Wrap a notebook tab's content in a vertically-scrollable Canvas.
        Returns the inner Frame to add controls into. The classic tk
        scroll trick: Canvas + Scrollbar + Frame-in-create_window, with
        <Configure> bindings to keep scrollregion and width in sync."""
        canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(canvas_window, width=e.width))

        # Mouse wheel — bind only while the pointer is inside this canvas
        # so other widgets on the page still get their own wheel events.
        def _bind_wheel(_e):
            canvas.bind_all("<MouseWheel>",
                            lambda ev: canvas.yview_scroll(int(-1 * (ev.delta / 120)), "units"))
        def _unbind_wheel(_e):
            canvas.unbind_all("<MouseWheel>")
        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)
        inner.bind("<Enter>", _bind_wheel)
        inner.bind("<Leave>", _unbind_wheel)

        return inner

    def _setting_block(self, parent, label: str, build_control, help_text: str | None = None):
        """One vertically-stacked setting: bold label, control row, optional
        dim help text. Each block packs into the scrollable parent, so the
        whole tab flows naturally without grid-row arithmetic."""
        block = ttk.Frame(parent)
        block.pack(fill="x", padx=14, pady=(12, 0))
        ttk.Label(block, text=label, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ctrl = ttk.Frame(block)
        ctrl.pack(fill="x", pady=(4, 2))
        build_control(ctrl)
        if help_text:
            ttk.Label(
                block, text=help_text, foreground="#666",
                font=("Segoe UI", 9), wraplength=600, justify="left",
            ).pack(anchor="w", pady=(0, 4))

    def _slider_inline(self, parent, var: tk.IntVar, lo: int, hi: int):
        scale = ttk.Scale(parent, from_=lo, to=hi, variable=var,
                          command=lambda v: var.set(int(float(v))))
        scale.pack(side="left", fill="x", expand=True)
        ttk.Label(parent, textvariable=var, width=5, anchor="e"
                 ).pack(side="right", padx=(8, 0))

    # -- tab construction --------------------------------------------------

    def _build_tab(self, parent, screen: int) -> dict[str, tk.Variable]:
        s = self.config["screens"][str(screen)]
        vars_: dict[str, tk.Variable] = {}

        # Background image picker
        def _bg(p):
            bg_var = tk.StringVar(value=s["bgImage"])
            vars_["bgImage"] = bg_var
            ttk.Entry(p, textvariable=bg_var).pack(side="left", fill="x", expand=True)
            ttk.Button(p, text="Browse…",
                       command=lambda: self._pick_image(bg_var)).pack(side="right", padx=(8, 0))
        self._setting_block(
            parent, "Background image", _bg,
            "Image displayed behind the glow layer. Use a PNG with transparent "
            "regions where you want the SignalRGB colours to shine through — JPG "
            "and WebP also work for fully-opaque backgrounds. Tip: the "
            "Build Wallpaper… tray menu can carve transparency out of any image.",
        )

        # Image fit
        def _fit(p):
            fit_var = tk.StringVar(value=s["bgFit"] if s["bgFit"] in BG_FIT_CHOICES else "cover")
            vars_["bgFit"] = fit_var
            ttk.OptionMenu(p, fit_var, fit_var.get(), *BG_FIT_CHOICES
                          ).pack(side="left", fill="x", expand=True)
        self._setting_block(
            parent, "Image fit", _fit,
            "How the background image fills the screen. 'cover' preserves aspect "
            "ratio and crops the overflowing edges; 'contain' shows the whole "
            "image with letterboxing; 'fill' stretches it to exactly the screen "
            "dimensions (will distort).",
        )

        # Image dim
        def _dim(p):
            dim_var = tk.IntVar(value=int(s["bgDim"]))
            vars_["bgDim"] = dim_var
            self._slider_inline(p, dim_var, 0, 100)
        self._setting_block(
            parent, "Image dim (%)", _dim,
            "Darkens the background image. 0 = original brightness, 100 = fully "
            "black. Useful when the wallpaper is bright and competes with the "
            "glow — bumping dim to 30-50 makes the colours pop.",
        )

        # Glow layout
        def _layout(p):
            layout_var = tk.StringVar(value=s["barLayout"])
            vars_["barLayout"] = layout_var
            labels = [label for _key, label in LAYOUT_CHOICES]
            label_to_key = {label: key for key, label in LAYOUT_CHOICES}
            current_label = next(
                (label for key, label in LAYOUT_CHOICES if key == layout_var.get()),
                labels[0],
            )
            display_var = tk.StringVar(value=current_label)
            def _on_change(lbl: str):
                layout_var.set(label_to_key.get(lbl, "lay-grid"))
            ttk.OptionMenu(p, display_var, current_label, *labels, command=_on_change
                          ).pack(side="left", fill="x", expand=True)
        self._setting_block(
            parent, "Glow layout", _layout,
            "How the colours from SignalRGB are rendered. Pixel Grid (2D) maps "
            "the full N×N matrix, one cell per LED. Vertical/Horizontal Stripes "
            "show wide bands across the screen. Centered Pills looks like a "
            "sound visualiser. Hidden disables the glow (image-only).",
        )

        # Enable glow
        def _show(p):
            show_var = tk.BooleanVar(value=bool(s["showBars"]))
            vars_["showBars"] = show_var
            ttk.Checkbutton(p, text="Show the glow layer", variable=show_var
                           ).pack(side="left")
        self._setting_block(
            parent, "Enable glow", _show,
            "Master on/off. When off, only the background image is shown — useful "
            "for previewing the image alone before adding the glow back.",
        )

        # Glow strength
        def _gs(p):
            gs_var = tk.IntVar(value=int(s["glowStrength"]))
            vars_["glowStrength"] = gs_var
            self._slider_inline(p, gs_var, 0, 200)
        self._setting_block(
            parent, "Glow strength (%)", _gs,
            "Brightness multiplier on the glow layer. 100 = baseline, 200 = "
            "double-bright (good for dark wallpapers / dim ambient light), "
            "0 = invisible.",
        )

        # Grid blur
        def _gb(p):
            gb_var = tk.IntVar(value=int(s["gridBlur"]))
            vars_["gridBlur"] = gb_var
            self._slider_inline(p, gb_var, 0, 200)
        self._setting_block(
            parent, "Grid blur (px)", _gb,
            "Softens the seams between adjacent grid cells. 0 = sharp pixel "
            "grid (visible cells), 200 = creamy gradient across the screen. "
            "Pixel Grid layout only.",
        )

        # Stripes blur
        def _sb(p):
            sb_var = tk.IntVar(value=int(s["stripesBlur"]))
            vars_["stripesBlur"] = sb_var
            self._slider_inline(p, sb_var, 0, 200)
        self._setting_block(
            parent, "Stripes blur (px)", _sb,
            "Softens the edges between stripes. Vertical/Horizontal Stripes "
            "layouts only.",
        )

        # Bar height
        def _bh(p):
            bh_var = tk.IntVar(value=int(s["barHeight"]))
            vars_["barHeight"] = bh_var
            self._slider_inline(p, bh_var, 10, 100)
        self._setting_block(
            parent, "Bar height (% of screen)", _bh,
            "Pill height as a percent of screen height. Centered Pills layout only.",
        )

        # Bar width
        def _bw(p):
            bw_var = tk.IntVar(value=int(s["barWidth"]))
            vars_["barWidth"] = bw_var
            self._slider_inline(p, bw_var, 1, 50)
        self._setting_block(
            parent, "Bar width (‰ of screen)", _bw,
            "Pill width in per-mille (thousandths) of screen width. Centered "
            "Pills layout only — keep low for thin bars, raise for chunky ones.",
        )

        # Debug overlay
        def _dbg(p):
            ss_var = tk.BooleanVar(value=bool(s["showStatus"]))
            vars_["showStatus"] = ss_var
            ttk.Checkbutton(p, text="Show top-left status line", variable=ss_var
                           ).pack(side="left")
        self._setting_block(
            parent, "Show debug overlay", _dbg,
            "Tiny status line in the top-left of the wallpaper showing the "
            "bridge connection state and current frame rate. Useful for "
            "troubleshooting; leave off in normal use.",
        )

        # Bottom padding so the last block has breathing room when scrolled.
        ttk.Frame(parent, height=12).pack(fill="x")
        return vars_

    def _pick_image(self, var: tk.StringVar):
        path = filedialog.askopenfilename(
            title="Pick background image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp *.svg *.bmp"),
                       ("All files", "*.*")],
        )
        if path:
            var.set(path)

    # -- save / cancel ------------------------------------------------------

    def _on_save(self):
        # Collect every Var into the in-memory config (the dialog received a
        # deep-copy so we won't disturb the live config until the caller
        # accepts it).
        try:
            self.config["screenCount"] = max(1, min(N_SCREENS, int(self.global_vars["screenCount"].get())))
        except Exception:
            self.config["screenCount"] = 1
        try:
            self.config["fullscreenPause"] = bool(self.global_vars["fullscreenPause"].get())
        except Exception:
            self.config["fullscreenPause"] = True
        for n in range(N_SCREENS):
            settings = {k: var.get() for k, var in self.vars[n].items()}
            self.config["screens"][str(n)] = settings
        # Caller persists + pushes to live wallpapers. We deliberately keep
        # the dialog open so the user can iterate (test, switch tabs, tweak
        # the next screen) without re-opening it from the tray every time.
        self.on_save(self.config)
        if self._saved_label is not None:
            self._saved_label.config(text="✓ Saved at " + time.strftime("%H:%M:%S"))

    def _on_close(self):
        if self.root is not None:
            self.root.destroy()


# ============================================================================
# About dialog
# ============================================================================

class AboutDialog:
    """Standalone Tk window with version info, author block + avatar, and
    quick links. The full open-source attributions live in docs/credits.md
    on GitHub now — the dialog links to them instead of embedding the wall
    of text. Spawned per tray click, on its own daemon thread."""

    # Class-level cache so a second About-open during the same process
    # doesn't re-hit GitHub for the avatar.
    _avatar_pil_cached: "Image.Image | None" = None

    def _get_avatar(self) -> "Image.Image | None":
        if AboutDialog._avatar_pil_cached is not None:
            return AboutDialog._avatar_pil_cached
        try:
            req = urllib.request.Request(
                f"https://github.com/{APP_GITHUB_USER}.png?size=128",
                headers={"User-Agent": f"SignalRGBWallpaper-About/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = r.read()
            img = Image.open(BytesIO(data)).convert("RGBA")
            img.thumbnail((96, 96), Image.LANCZOS)
            AboutDialog._avatar_pil_cached = img
            return img
        except Exception as e:
            print(f"[about] avatar fetch failed: {e}")
            return None

    def show(self):
        root = tk.Tk()
        root.title(tr("about.title", app=APP_NAME))
        root.geometry("520x420")
        root.minsize(480, 380)

        # Title block
        ttk.Label(root, text=APP_NAME,
                  font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(18, 0))
        ttk.Label(root, text=tr("about.version", ver=APP_VERSION),
                  foreground="#666").pack(anchor="w", padx=18, pady=(0, 12))

        # Author card: avatar (left) + name + GitHub handle + copyright (right)
        author = ttk.Frame(root)
        author.pack(fill="x", padx=18, pady=(0, 6))

        avatar_img = self._get_avatar()
        if avatar_img is not None:
            try:
                photo = ImageTk.PhotoImage(avatar_img, master=root)
                avatar_lbl = ttk.Label(author, image=photo)
                avatar_lbl.image = photo   # keep a ref so Tk doesn't GC it
                avatar_lbl.pack(side="left", padx=(0, 14))
            except Exception as e:
                print(f"[about] tk image failed: {e}")

        text_col = ttk.Frame(author)
        text_col.pack(side="left", fill="x", expand=True)
        ttk.Label(text_col, text=APP_AUTHOR,
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        handle_text = tr("about.github_handle", user=APP_GITHUB_USER)
        handle_lbl = ttk.Label(text_col, text=handle_text,
                               foreground="#3a6ba8", cursor="hand2")
        handle_lbl.pack(anchor="w")
        handle_lbl.bind("<Button-1>", lambda _e: webbrowser.open(APP_AUTHOR_URL))
        ttk.Label(text_col,
                  text=tr("about.copyright", author=APP_AUTHOR),
                  foreground="#666").pack(anchor="w", pady=(8, 0))

        # One-line tagline
        ttk.Separator(root).pack(fill="x", padx=18, pady=(14, 12))
        ttk.Label(root, text=tr("about.tagline"),
                  wraplength=460, foreground="#444"
                  ).pack(anchor="w", padx=18, pady=(0, 14))

        # Quick links
        links = ttk.Frame(root)
        links.pack(fill="x", padx=18, pady=(0, 6))
        ttk.Button(links, text=tr("about.btn.github"),
                   command=lambda: webbrowser.open(APP_REPO)).pack(side="left")
        ttk.Button(links, text=tr("about.btn.license"),
                   command=lambda: webbrowser.open(APP_REPO + "/blob/main/LICENSE")
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(links, text=tr("about.btn.credits"),
                   command=lambda: webbrowser.open(APP_CREDITS_URL)
                   ).pack(side="left", padx=(6, 0))

        donate = ttk.Frame(root)
        donate.pack(fill="x", padx=18, pady=(2, 6))
        ttk.Button(donate, text=tr("about.btn.donate"),
                   command=lambda: webbrowser.open(APP_DONATE_URL)).pack(side="left")

        # Footer / close
        btn_row = ttk.Frame(root)
        btn_row.pack(fill="x", padx=18, pady=(16, 14), side="bottom")
        ttk.Button(btn_row, text=tr("about.btn.close"),
                   command=root.destroy).pack(side="right")

        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()


# ============================================================================
# System Status dialog
# ============================================================================

class SystemStatusDialog:
    """Tk dialog that shows green/red rows for each "is the install
    actually working?" signal and offers a one-click *Fix this…* button
    per red row. Spawned per tray click on a daemon thread."""

    def __init__(self, bridge: BridgeRuntime):
        self.bridge = bridge

    def show(self):
        status = self.bridge.get_health_status()
        root = tk.Tk()
        root.title(tr("status.title"))
        root.geometry("520x360")
        root.minsize(460, 320)

        ttk.Label(root, text=tr("status.title"),
                  font=("Segoe UI", 13, "bold")).pack(
                      anchor="w", padx=18, pady=(16, 0))
        ttk.Label(root, text=tr("status.subtitle"),
                  foreground="#666").pack(
                      anchor="w", padx=18, pady=(0, 12))

        rows = ttk.Frame(root)
        rows.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        # Build each status row. `(ok, label, fix_label, fix_action)`.
        # `fix_action` is None when there's nothing useful to do — the
        # row still renders a red dot but no button.
        def open_plugin_dir():
            try:
                Path(status["plugin_dir"]).mkdir(parents=True, exist_ok=True)
                os.startfile(status["plugin_dir"])
            except Exception as e:
                print(f"[status] open plugin dir failed: {e}")

        def open_signalrgb_dl():
            webbrowser.open("https://signalrgb.com/")

        def open_lhm_dl():
            webbrowser.open("https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases")

        def open_help_pages():
            try: webbrowser.open(f"http://{WS_HOST}:{WS_PORT}/help")
            except Exception: pass

        entries = [
            (status["plugin_present"],
             tr("status.plugin"),
             tr("status.btn.open_plugins"),
             open_plugin_dir),
            (status["signalrgb_running"],
             tr("status.signalrgb"),
             tr("status.btn.get_signalrgb"),
             open_signalrgb_dl),
            (True,
             tr("status.bridge", host=WS_HOST, port=WS_PORT),
             None, None),  # if this dialog renders, the bridge is up
            (status["pages_connected"] > 0,
             tr("status.pages", n=status["pages_connected"]),
             tr("status.btn.help"),
             open_help_pages),
        ]
        # LHM row only appears if a Hardware-sensor widget is in use —
        # otherwise its status is irrelevant.
        if status["lhm_widget_present"]:
            entries.append((
                status["lhm_online"],
                tr("status.lhm", n=status["lhm_count"]),
                tr("status.btn.get_lhm"),
                open_lhm_dl,
            ))

        for ok, label, fix_label, fix_action in entries:
            row = ttk.Frame(rows)
            row.pack(fill="x", pady=4)
            dot = tk.Label(row, text="●", font=("Segoe UI", 16),
                           fg=("#3aa86d" if ok else "#cc4a4a"))
            dot.pack(side="left", padx=(0, 10))
            ttk.Label(row, text=label,
                      wraplength=320, justify="left").pack(
                          side="left", fill="x", expand=True)
            if not ok and fix_action is not None and fix_label:
                ttk.Button(row, text=fix_label,
                           command=fix_action).pack(side="right")

        # Footer
        btn_row = ttk.Frame(root)
        btn_row.pack(fill="x", padx=18, pady=(8, 14), side="bottom")
        ttk.Button(btn_row, text=tr("status.btn.refresh"),
                   command=lambda: (root.destroy(),
                                    SystemStatusDialog(self.bridge).show())
                  ).pack(side="left")
        ttk.Button(btn_row, text=tr("about.btn.close"),
                   command=root.destroy).pack(side="right")

        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()


# ============================================================================
# Tray icon
# ============================================================================

def build_tray_image() -> Image.Image:
    """Generate a 64x64 tray icon: monitor with five RGB pads underneath."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Monitor body
    d.rounded_rectangle((6, 8, 58, 42), radius=3, outline=(74, 81, 96, 255), width=2, fill=(27, 31, 42, 255))
    d.rectangle((10, 12, 54, 38), fill=(5, 6, 8, 255))
    # Stand
    d.rectangle((26, 46, 38, 49), fill=(74, 81, 96, 255))
    d.rectangle((20, 50, 44, 52), fill=(74, 81, 96, 255))
    # Five RGB pads under the screen edge
    pad_colors = [(255, 45, 106), (255, 143, 45), (255, 233, 45), (66, 255, 133), (45, 180, 255)]
    centers = [17, 25, 33, 41, 49]
    for cx, color in zip(centers, pad_colors):
        d.ellipse((cx - 3, 25, cx + 3, 31), fill=color + (255,))
    return img


class TrayApp:
    def __init__(self, bridge: BridgeRuntime, config: dict, config_lock: threading.Lock):
        self.bridge = bridge
        self.config = config
        self.config_lock = config_lock
        self.icon: pystray.Icon | None = None
        # Background update checker — polls GitHub releases daily + on demand.
        # Callbacks refresh the tray menu so the "Update available" entry
        # and "last checked" timestamps stay live without a restart.
        self.update_checker = UpdateChecker(
            config, config_lock,
            on_update_available=self._on_update_available,
            on_check_done=self._on_update_check_done,
        )

    def run(self):
        # Top-level menu is dynamic so the "Update available…" entry can
        # appear / disappear based on the checker's state without
        # rebuilding the Icon.
        menu = pystray.Menu(self._build_top_menu)
        self.icon = pystray.Icon(
            name="SignalRGBWallpaper",
            icon=build_tray_image(),
            title="SignalRGB Wallpaper Bridge",
            menu=menu,
        )
        self.update_checker.start()
        self.icon.run()

    def _build_top_menu(self):
        items = []
        avail = self.update_checker.available()
        if avail:
            tag, _ = avail
            has_installer = self.update_checker.available_asset() is not None
            items.append(pystray.MenuItem(
                tr("updates.available_top", tag=tag),
                self._open_update_page))
            # Only offer the one-click install when the release ships
            # an installer asset (older betas didn't always).
            if has_installer:
                items.append(pystray.MenuItem(
                    tr("updates.install_now", tag=tag),
                    self._download_and_install_update))
            items.append(pystray.Menu.SEPARATOR)
        # Cheap snapshot of the lock state across active screens so the
        # Lock/Unlock entry can switch label without opening a submenu.
        any_unlocked = self._any_screen_unlocked()
        items.extend([
            pystray.MenuItem(tr("tray.configurator"), self._open_configurator, default=True),
            pystray.MenuItem(tr("tray.builder"),      self._open_builder),
            pystray.MenuItem(tr("tray.help"),         self._open_help),
            pystray.MenuItem(tr("tray.status"),       self._open_status),
            pystray.MenuItem(
                tr("tray.lock_all") if any_unlocked else tr("tray.unlock_all"),
                self._toggle_widgets_lock_all),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(tr("tray.advanced"), pystray.Menu(
                pystray.MenuItem(tr("tray.quick_add_widget"), pystray.Menu(self._widget_menu_items)),
                pystray.MenuItem(tr("tray.quick_effects"),    pystray.Menu(self._effects_menu_items)),
                pystray.MenuItem(
                    tr("tray.preset_hotkeys"),
                    self._toggle_preset_hotkeys,
                    checked=lambda _i: self._preset_hotkeys_enabled()),
                pystray.MenuItem(tr("tray.reload_config"),    self._reload_config),
            )),
            pystray.MenuItem(tr("tray.updates"), pystray.Menu(self._update_menu_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(tr("tray.about"), self._open_about),
            pystray.MenuItem(tr("tray.quit"),  self._quit),
        ])
        return items

    def _open_configurator(self, icon, item):
        url = f"http://{WS_HOST}:{WS_PORT}/configurator"
        try: webbrowser.open(url, new=2)
        except Exception as e: print(f"[tray] open configurator failed: {e}")

    # ── Top-level Lock / Unlock toggle ─────────────────────────────────
    # Picks the dominant state across all active screens — if any screen
    # is currently unlocked, the toggle locks them all; otherwise unlocks
    # them all. Keeps the per-screen Configurator + tray-Advanced flow
    # intact for users who need fine-grained control.

    def _any_screen_unlocked(self) -> bool:
        with self.config_lock:
            n = max(1, min(N_SCREENS, int(self.config.get("screenCount", 1))))
            for i in range(n):
                s = self.config["screens"].get(str(i), {})
                if s.get("widgetsLocked") is False:
                    return True
        return False

    def _toggle_widgets_lock_all(self, icon, item):
        target_locked = self._any_screen_unlocked()    # if any unlocked → lock everything
        with self.config_lock:
            n = max(1, min(N_SCREENS, int(self.config.get("screenCount", 1))))
        for i in range(n):
            self.bridge.set_widgets_locked(i, target_locked)
        print(f"[tray] all screens widgetsLocked → {target_locked}")

    def _preset_hotkeys_enabled(self) -> bool:
        with self.config_lock:
            return bool(self.config.get("presetHotkeysEnabled", False))

    def _toggle_preset_hotkeys(self, icon, item):
        new_value = not self._preset_hotkeys_enabled()
        self.bridge.update_bridge_setting("presetHotkeysEnabled", new_value)
        # pystray queries `checked` lazily; redraw the menu so the
        # checkmark reflects the new state without a Windows mouse-out.
        try: icon.update_menu()
        except Exception: pass

    # -- menu callbacks (fire on pystray's worker thread) -------------------

    def _open_settings(self, icon, item):
        threading.Thread(target=self._show_settings_dialog, daemon=True,
                         name="settings-dialog").start()

    def _show_settings_dialog(self):
        # Snapshot under lock so the dialog gets a stable view; the dialog's
        # save callback will re-acquire the lock when mutating.
        with self.config_lock:
            cfg_view = json.loads(json.dumps(self.config))  # deep copy

        def on_save(updated_config: dict):
            # Replace the live config wholesale (covers screenCount + all
            # per-screen settings), persist to disk, and push every screen's
            # settings to any connected wallpaper pages.
            with self.config_lock:
                self.config.clear()
                self.config.update(updated_config)
                cfg_snapshot = json.loads(json.dumps(updated_config))
            try:
                save_config(cfg_snapshot)
            except Exception as e:
                print(f"[tray] save_config failed: {e}")
            for n in range(N_SCREENS):
                self.bridge.push_settings(n, cfg_snapshot["screens"][str(n)])

        dialog = SettingsDialog(cfg_view, on_save)
        try:
            dialog.show()
        except Exception as e:
            print(f"[tray] settings dialog crashed: {e}")

    def _open_about(self, icon, item):
        threading.Thread(target=self._show_about_dialog, daemon=True,
                         name="about-dialog").start()

    def _show_about_dialog(self):
        try:
            AboutDialog().show()
        except Exception as e:
            print(f"[tray] about dialog crashed: {e}")

    def _open_status(self, icon, item):
        threading.Thread(target=self._show_status_dialog, daemon=True,
                         name="status-dialog").start()

    def _show_status_dialog(self):
        try:
            SystemStatusDialog(self.bridge).show()
        except Exception as e:
            print(f"[tray] status dialog crashed: {e}")

    def _open_builder(self, icon, item):
        # Open the bundled HTML wallpaper builder in the user's default
        # browser. The bridge serves it at /builder on the same port the
        # WS / image proxy listen on, so the URL is always reachable when
        # the bridge is running.
        url = f"http://{WS_HOST}:{WS_PORT}/builder"
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            print(f"[tray] failed to open browser: {e}")

    def _open_help(self, icon, item):
        # Help page — scenario walkthroughs (1/2/3/4 monitors × Lively /
        # Wallpaper Engine) plus a Tips section. Same browser-served
        # pattern as Configurator / Builder.
        url = f"http://{WS_HOST}:{WS_PORT}/help"
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            print(f"[tray] failed to open browser: {e}")

    # ── Updates submenu ────────────────────────────────────────────────
    # Manual trigger + the two toggles + a status line ("up-to-date /
    # last error / pending"). Rebuilt on every open so the status reflects
    # the latest poll without any push from the checker side.

    def _update_menu_items(self):
        with self.config_lock:
            enabled = bool(self.config.get("updateCheckEnabled", True))
            beta    = bool(self.config.get("allowBetas", False))
        avail   = self.update_checker.available()
        last_t  = self.update_checker.last_checked()
        err     = self.update_checker.last_error()
        items = [
            pystray.MenuItem(tr("updates.check_now"),  self._check_updates_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(tr("updates.enable"),     self._toggle_update_enabled,
                             checked=lambda _it, _e=enabled: _e),
            pystray.MenuItem(tr("updates.allow_beta"), self._toggle_allow_betas,
                             checked=lambda _it, _b=beta: _b),
            pystray.Menu.SEPARATOR,
        ]
        if avail:
            tag, _ = avail
            items.append(pystray.MenuItem(
                tr("updates.latest", tag=tag),
                self._open_update_page))
        elif err:
            short = (err[:48] + "…") if len(err) > 48 else err
            items.append(pystray.MenuItem(tr("updates.last_failed", err=short),
                                          None, enabled=False))
        elif last_t > 0:
            ago = max(0, int(time.time() - last_t))
            if   ago < 60:   ago_s = tr("ago.s", n=ago)
            elif ago < 3600: ago_s = tr("ago.m", n=ago // 60)
            else:            ago_s = tr("ago.h", n=ago // 3600)
            items.append(pystray.MenuItem(tr("updates.up_to_date", ago=ago_s),
                                          None, enabled=False))
        else:
            items.append(pystray.MenuItem(tr("updates.not_checked"),
                                          None, enabled=False))
        items.append(pystray.MenuItem(tr("updates.installed", ver=APP_VERSION),
                                      None, enabled=False))
        return items

    def _check_updates_now(self, icon, item):
        self.update_checker.check_now()

    def _open_update_page(self, icon, item):
        avail = self.update_checker.available()
        url = avail[1] if avail else UPDATE_RELEASES_HTML
        try: webbrowser.open(url, new=2)
        except Exception as e: print(f"[tray] open release page failed: {e}")

    def _download_and_install_update(self, icon, item):
        """Tray entry: download the pending update's installer to %TEMP%
        and launch it silently. The bridge exits once the installer is
        running so it can replace SignalRGBBridge.exe in place; the
        installer's [Run] section re-launches the new bridge."""
        avail = self.update_checker.available()
        if not avail:
            return
        tag = avail[0]
        # Use a tiny Tk window for progress so the user knows the
        # download is happening (the installer asset is ~20 MB so a
        # cold-cache download can take a few seconds). Falls back to a
        # console-only path if Tk isn't available for some reason.
        def show_progress_window():
            root = tk.Tk()
            root.title(tr("updates.installing_title", tag=tag))
            root.geometry("440x140")
            root.resizable(False, False)
            label_var = tk.StringVar(value=tr("updates.installing_start"))
            ttk.Label(root, textvariable=label_var,
                      wraplength=400, justify="left").pack(
                          anchor="w", padx=18, pady=(18, 6))
            pb = ttk.Progressbar(root, mode="determinate", length=400, maximum=100)
            pb.pack(padx=18, pady=6)
            ttk.Label(root, text=tr("updates.installing_hint"),
                      foreground="#888",
                      wraplength=400).pack(anchor="w", padx=18, pady=(0, 10))
            def on_progress(done, total):
                pct = (done * 100 / total) if total > 0 else 0
                root.after(0, lambda: (
                    pb.configure(value=pct),
                    label_var.set(tr("updates.installing_progress",
                                     pct=int(pct),
                                     done_mb=done // (1024*1024),
                                     total_mb=(total // (1024*1024)) if total else 0))
                ))
            def on_done(path, err):
                root.after(0, lambda: (
                    label_var.set(tr("updates.installing_done") if path
                                  else tr("updates.installing_failed", msg=err or "")),
                ))
                # Don't auto-close — the os._exit kills this window too
                # when the bridge dies.
            self.update_checker.download_and_install(on_progress, on_done)
            root.mainloop()
        threading.Thread(target=show_progress_window, daemon=True,
                         name="update-progress").start()

    def _toggle_update_enabled(self, icon, item):
        with self.config_lock:
            cur = bool(self.config.get("updateCheckEnabled", True))
            self.config["updateCheckEnabled"] = not cur
            snap = json.loads(json.dumps(self.config))
        try: save_config(snap)
        except Exception as e: print(f"[tray] save_config failed: {e}")
        if not cur:    # we just enabled it → check now
            self.update_checker.check_now()

    def _toggle_allow_betas(self, icon, item):
        with self.config_lock:
            cur = bool(self.config.get("allowBetas", False))
            self.config["allowBetas"] = not cur
            snap = json.loads(json.dumps(self.config))
        try: save_config(snap)
        except Exception as e: print(f"[tray] save_config failed: {e}")
        # Re-check immediately so the user sees the effect of flipping
        # the prerelease filter without waiting a day.
        self.update_checker.check_now()

    def _on_update_available(self, tag: str, url: str):
        # Balloon notification — fires once per detected version bump.
        try:
            if self.icon:
                self.icon.notify(
                    tr("updates.balloon_msg", tag=tag),
                    tr("updates.balloon_title"),
                )
        except Exception as e:
            print(f"[tray] notify failed: {e}")
        # Force a menu rebuild so the "Update available" entry appears.
        try:
            if self.icon: self.icon.update_menu()
        except Exception: pass

    def _on_update_check_done(self, found: bool, error: str | None):
        # Refresh menu so the "last checked …s ago" status updates.
        try:
            if self.icon: self.icon.update_menu()
        except Exception: pass

    # ── Effects submenu ────────────────────────────────────────────────
    # Per-screen ambient preset / pixelfx mode / tint toggle. Live-pushed
    # to the wallpaper via the existing settings-broadcast pipeline.

    # i18n keys instead of raw labels — the actual text comes from tr() at
    # menu-build time, so a language change after first render reflects on
    # the next open.
    AMBIENT_PRESETS_TRAY = [
        ("off",    "ambient.off"),
        ("snow",   "ambient.snow"),
        ("rain",   "ambient.rain"),
        ("sparks", "ambient.sparks"),
        ("aurora", "ambient.aurora"),
    ]
    PIXELFX_MODES_TRAY = [
        ("off",    "pixelfx.off"),
        ("trail",  "pixelfx.trail"),
        ("glow",   "pixelfx.glow"),
        ("ripple", "pixelfx.ripple"),
        ("all",    "pixelfx.all"),
    ]

    def _effects_menu_items(self):
        with self.config_lock:
            n = max(1, min(N_SCREENS, int(self.config.get("screenCount", 1))))
        return [
            pystray.MenuItem(tr("tray.screen_n", n=i + 1),
                             pystray.Menu(self._effects_screen_items_factory(i)))
            for i in range(n)
        ]

    def _effects_screen_items_factory(self, screen: int):
        def items():
            with self.config_lock:
                s = self.config["screens"].get(str(screen), {})
                current_ambient = s.get("ambientEffect", "off")
                tint            = bool(s.get("ambientTint", False))
                current_pixelfx = s.get("pixelfx", "off")
            menu = []
            # Ambient preset radio list
            menu.append(pystray.MenuItem(tr("effects.ambient_label"),
                                         None, enabled=False))
            for value, key in self.AMBIENT_PRESETS_TRAY:
                menu.append(pystray.MenuItem(
                    "  " + tr(key),
                    self._set_ambient_factory(screen, value),
                    checked=lambda _it, _v=value, _c=current_ambient: _v == _c,
                    radio=True,
                ))
            menu.append(pystray.Menu.SEPARATOR)
            menu.append(pystray.MenuItem(
                tr("effects.tint_with_glow"),
                self._toggle_ambient_tint_factory(screen),
                checked=lambda _it, _t=tint: _t,
            ))
            menu.append(pystray.Menu.SEPARATOR)
            menu.append(pystray.MenuItem(tr("effects.pixelfx_label"),
                                         None, enabled=False))
            for value, key in self.PIXELFX_MODES_TRAY:
                menu.append(pystray.MenuItem(
                    "  " + tr(key),
                    self._set_pixelfx_factory(screen, value),
                    checked=lambda _it, _v=value, _c=current_pixelfx: _v == _c,
                    radio=True,
                ))
            return menu
        return items

    def _set_ambient_factory(self, screen: int, value: str):
        def handler(icon, item):
            with self.config_lock:
                s = self.config["screens"].setdefault(str(screen), {})
                s["ambientEffect"] = value
                snap = json.loads(json.dumps(s))
                full_snap = json.loads(json.dumps(self.config))
            try: save_config(full_snap)
            except Exception as e: print(f"[tray] save_config failed: {e}")
            self.bridge.push_settings(screen, snap)
            print(f"[tray] screen={screen} ambientEffect → {value}")
        return handler

    def _set_pixelfx_factory(self, screen: int, value: str):
        def handler(icon, item):
            with self.config_lock:
                s = self.config["screens"].setdefault(str(screen), {})
                s["pixelfx"] = value
                snap = json.loads(json.dumps(s))
                full_snap = json.loads(json.dumps(self.config))
            try: save_config(full_snap)
            except Exception as e: print(f"[tray] save_config failed: {e}")
            self.bridge.push_settings(screen, snap)
            print(f"[tray] screen={screen} pixelfx → {value}")
        return handler

    def _toggle_ambient_tint_factory(self, screen: int):
        def handler(icon, item):
            with self.config_lock:
                s = self.config["screens"].setdefault(str(screen), {})
                s["ambientTint"] = not bool(s.get("ambientTint", False))
                snap = json.loads(json.dumps(s))
                full_snap = json.loads(json.dumps(self.config))
            try: save_config(full_snap)
            except Exception as e: print(f"[tray] save_config failed: {e}")
            self.bridge.push_settings(screen, snap)
            print(f"[tray] screen={screen} ambientTint → {s['ambientTint']}")
        return handler

    # ── Widgets submenu ────────────────────────────────────────────────
    # Two layers of dynamic menus: outer = one entry per active screen
    # (driven by current screenCount), inner = Edit-toggle + per-type
    # Add items. Both rebuild on every menu open so screenCount changes
    # land without restarting the tray.

    def _widget_menu_items(self):
        with self.config_lock:
            n = max(1, min(N_SCREENS, int(self.config.get("screenCount", 1))))
        items = []
        for i in range(n):
            items.append(pystray.MenuItem(
                tr("tray.screen_n", n=i + 1),
                pystray.Menu(self._widget_screen_items_factory(i)),
            ))
        return items

    def _widget_screen_items_factory(self, screen: int):
        def items():
            with self.config_lock:
                s = self.config["screens"].get(str(screen), {})
                locked = bool(s.get("widgetsLocked", True))
                count  = len(s.get("widgets", []))
            state = tr("widgets.state.locked") if locked else tr("widgets.state.edit")
            menu = [
                pystray.MenuItem(
                    tr("widgets.edit_toggle", state=state),
                    self._toggle_widgets_lock_factory(screen),
                    checked=lambda _it, _locked=locked: not _locked,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(tr("widgets.placed_count", n=count),
                                 None, enabled=False),
                pystray.Menu.SEPARATOR,
            ]
            # Generate one "Add <Label>" entry per registered widget type.
            # Widget labels stay in English for now — they're proper nouns
            # ("Clock", "Calendar", …) and changing them per locale would
            # diverge from the labels shown in the in-browser picker.
            for wtype, cfg in WIDGET_DEFAULTS.items():
                label = cfg.get("label", wtype.title())
                menu.append(pystray.MenuItem(tr("widgets.add_x", label=label),
                                             self._add_widget_factory(screen, wtype)))
            return menu
        return items

    def _toggle_widgets_lock_factory(self, screen: int):
        def handler(icon, item):
            with self.config_lock:
                s = self.config["screens"].get(str(screen), {})
                new_locked = not bool(s.get("widgetsLocked", True))
            self.bridge.set_widgets_locked(screen, new_locked)
            print(f"[tray] screen={screen} widgetsLocked → {new_locked}")
        return handler

    def _add_widget_factory(self, screen: int, widget_type: str):
        def handler(icon, item):
            self.bridge.add_widget(screen, widget_type)
            print(f"[tray] screen={screen} added widget: {widget_type}")
        return handler

    def _reload_config(self, icon, item):
        try:
            reloaded = load_config()
            with self.config_lock:
                self.config.clear()
                self.config.update(reloaded)
            # Push to every screen so live wallpapers refresh
            for n in range(N_SCREENS):
                self.bridge.push_settings(n, reloaded["screens"][str(n)])
            print("[tray] config reloaded from disk")
        except Exception as e:
            print(f"[tray] reload failed: {e}")

    def _quit(self, icon, item):
        # Hard-kill the process immediately.
        # Why not icon.stop() + graceful return: in --noconsole PyInstaller
        # builds stdout is closed (print would raise OSError, swallowed by
        # pystray) and icon.stop() called from a callback thread sometimes
        # blocks on the message-pump drain — we'd hang with the tray icon
        # gone but the process still alive (exactly the bug the user hit).
        # We have nothing worth flushing here: config is persisted on every
        # Save, no in-flight writes. os._exit bypasses atexit and threads
        # cleanly.
        os._exit(0)


# ============================================================================
# Main
# ============================================================================

def main():
    config = load_config()
    init_language(config)
    config_lock = threading.Lock()

    # Rebuild the library catalogue from the directory contents on every
    # startup. The installer copies its bundled `library.json` over the
    # user's, which lists only the starter wallpapers — without this
    # step, user-uploaded PNGs (still on disk) wouldn't appear in the
    # Configurator strip until the next upload/delete forces a rebuild.
    # `_library_rebuild_catalogue` preserves pin/order/addedAt for any
    # entries that survived the overwrite, so this is safe to run
    # unconditionally.
    try:
        _library_rebuild_catalogue(library_dir())
    except Exception as e:
        print(f"[library] startup rebuild failed: {e}")

    bridge = BridgeRuntime(config, config_lock)
    bridge.start()

    tray = TrayApp(bridge, config, config_lock)
    tray.run()  # blocks on Win32 message pump


if __name__ == "__main__":
    main()
