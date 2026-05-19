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
import json
import mimetypes
import os
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
from PIL import Image, ImageDraw


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

    def last_checked(self) -> float:
        return self._last_checked_ts

    def last_error(self) -> str | None:
        return self._last_error

    def check_now(self):
        threading.Thread(target=self._safe_check, daemon=True, name="update-check-now").start()

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
        if best > current:
            prev = self._available_tag
            self._available_tag = best_tag
            self._available_url = best_url
            if prev != best_tag:    # only fire on first detection / new bump
                print(f"[update] newer release available: {best_tag} (current {APP_VERSION})")
                try: self.on_update_available(best_tag, best_url)
                except Exception as e: print(f"[update] notify failed: {e}")
        else:
            self._available_tag = None
            self._available_url = None
            print(f"[update] no newer release; current {APP_VERSION} is up to date "
                  f"(allow_betas={allow_betas})")


# ============================================================================
# Constants
# ============================================================================

APP_NAME    = "SignalRGB Wallpaper Bridge"
APP_VERSION = "0.5.2-beta"
APP_AUTHOR  = "Delido"
APP_REPO    = "https://github.com/Delido/signalrgb-wallpaper"

UDP_HOST = "127.0.0.1"
UDP_PORT = 17320
WS_HOST  = "127.0.0.1"
WS_PORT  = 17320

# Max payload size accepted on POST /screen/<N>/background. Generous (50 MB)
# but bounded — the builder caps output well below this in practice.
MAX_BACKGROUND_UPLOAD_BYTES = 50 * 1024 * 1024

WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_SCREEN_INDEX = 7  # generous upper bound; plugin caps at 2 (3 screens)
N_SCREENS = 3

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
}

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


def screens_dir() -> Path:
    """Where builder-uploaded backgrounds get persisted, one file per
    screen with a unix-millis timestamp suffix so the browser can't cache
    a stale image after re-upload."""
    p = config_path().parent / "screens"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_config() -> dict:
    return {
        "version": CONFIG_VERSION,
        "screenCount": 1,         # plugin polls /config and announces this many controllers
        "fullscreenPause": True,  # auto-pause glow when a fullscreen app is active
        "updateCheckEnabled": True,
        "allowBetas":         False,   # include GitHub prerelease tags in update checks
        "screens": {str(n): dict(DEFAULT_SCREEN_SETTINGS) for n in range(N_SCREENS)},
    }


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
    cfg.setdefault("screens", {})
    for n in range(N_SCREENS):
        s = cfg["screens"].setdefault(str(n), {})
        for k, v in DEFAULT_SCREEN_SETTINGS.items():
            s.setdefault(k, v)
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
        self.clients_by_screen: dict[int, set] = {}
        self._lock = asyncio.Lock()

    def handle_client_message(self, screen: int, msg: dict):
        """Route a decoded JSON message from a wallpaper page. All widget
        mutations live here; future client→server messages slot in next to
        them. Runs on the asyncio loop thread."""
        t = msg.get("type")
        if t in ("widget-update", "widget-add", "widget-remove", "widgets-lock"):
            try:
                self.on_widget_command(screen, msg)
            except Exception as e:
                print(f"[ws] widget command failed: {e}")
        # Unknown types are silently dropped — clients on a newer protocol
        # version shouldn't crash an older bridge.

    # ----- client lifecycle -----

    async def add(self, writer, screen: int):
        async with self._lock:
            self.clients_by_screen.setdefault(screen, set()).add(writer)
            total = sum(len(s) for s in self.clients_by_screen.values())
        print(f"[+] ws screen={screen} (total: {total})")
        # Push current settings immediately so the page can paint with the
        # right background / layout before the first frame arrives.
        try:
            settings = self.get_settings(screen)
            writer.write(encode_text_frame(json.dumps({"type": "settings", "screen": screen, "data": settings})))
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
        msg = json.dumps({"type": "settings", "screen": screen, "data": settings})
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
        if method == "GET" and target.startswith("/config"):
            try:
                payload = json.dumps({"screenCount": int(self.get_screen_count())}).encode("utf-8")
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
        await self.add(writer, screen)
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


class UdpReceiver(asyncio.DatagramProtocol):
    def __init__(self, broadcaster: Broadcaster, loop: asyncio.AbstractEventLoop):
        self.broadcaster = broadcaster
        self.loop = loop
        self.count = 0
        self.warned_bad = 0

    def datagram_received(self, data: bytes, addr):
        if len(data) < 7 or data[0] != 0x53 or data[1] != 0x52:
            if self.warned_bad < 3:
                self.warned_bad += 1
                print(f"[udp] malformed datagram from {addr}: len={len(data)} head={data[:8].hex()}")
            return
        screen = data[2]
        self.count += 1
        if self.count == 1 or self.count % 600 == 0:
            print(f"[udp] {self.count} packets (last: screen={screen}, {len(data)} bytes)")
        self.loop.create_task(self.broadcaster.broadcast_frame(screen, data))


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
            return True
        except Exception as e:
            print(f"[bg] update failed: {e}")
            return False

    def push_settings(self, screen: int, settings: dict):
        if self.broadcaster:
            self.broadcaster.push_settings_threadsafe(screen, settings)

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
        return snap

    def remove_widget(self, screen: int, widget_id: str) -> dict | None:
        def mutate(s):
            s["widgets"] = [w for w in s.get("widgets", []) if w.get("id") != widget_id]
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
        return snap

    def update_widget(self, screen: int, widget_id: str, fields: dict) -> dict | None:
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
        return snap

    def set_widgets_locked(self, screen: int, locked: bool) -> dict | None:
        def mutate(s):
            s["widgetsLocked"] = bool(locked)
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
        return snap

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
        threading.Thread(target=run, daemon=True, name="widget-mutate").start()

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
    """Standalone Tk window with version info, repo link, and open-source
    attribution. Spawned per click on the tray's About item, on its own
    daemon thread, so it doesn't conflict with the Settings dialog or
    block the tray message pump."""

    def show(self):
        root = tk.Tk()
        root.title(f"About {APP_NAME}")
        root.geometry("560x520")
        root.minsize(520, 480)

        # Header
        ttk.Label(root, text=APP_NAME,
                  font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=16, pady=(16, 0))
        ttk.Label(root, text=f"Version {APP_VERSION}",
                  foreground="#666").pack(anchor="w", padx=16)
        ttk.Label(root, text=f"© 2026 {APP_AUTHOR}. MIT Licensed.",
                  foreground="#666").pack(anchor="w", padx=16, pady=(8, 0))

        # Quick links
        links = ttk.Frame(root)
        links.pack(fill="x", padx=16, pady=10)
        ttk.Button(links, text="Open on GitHub",
                   command=lambda: webbrowser.open(APP_REPO)).pack(side="left")
        ttk.Button(links, text="MIT License",
                   command=lambda: webbrowser.open(APP_REPO + "/blob/main/LICENSE")
                   ).pack(side="left", padx=(6, 0))

        ttk.Separator(root).pack(fill="x", padx=16, pady=(4, 8))
        ttk.Label(root, text="Open-source software used by this app",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16)

        oss_text = (
            "Bundled in SignalRGBBridge.exe:\n"
            "\n"
            "  • Python 3 — PSF License\n"
            "    https://www.python.org/  •  https://docs.python.org/3/license.html\n"
            "\n"
            "  • Python stdlib used at runtime: asyncio, http.server building\n"
            "    blocks, hashlib, base64, struct, urllib, json, mimetypes,\n"
            "    threading, webbrowser, tkinter (Settings & About dialogs)\n"
            "    — all under PSF License.\n"
            "\n"
            "  • pystray (system tray icon) — LGPL 3.0\n"
            "    https://github.com/moses-palmer/pystray\n"
            "\n"
            "  • Pillow / PIL (image library, tray-icon rendering) — MIT-CMU (HPND)\n"
            "    https://github.com/python-pillow/Pillow\n"
            "\n"
            "  • PyInstaller (single-file packager — used at build time, the\n"
            "    bootloader stub it embeds ships with this exe) — GPL 2.0+\n"
            "    with linking exception (commercial / closed-source apps OK).\n"
            "    https://github.com/pyinstaller/pyinstaller\n"
            "\n"
            "  • builder.html (the in-browser wallpaper editor served at\n"
            "    /builder) — vanilla HTML5 / CSS / JS, no third-party JS\n"
            "    or CSS frameworks. Uses only native browser APIs (Canvas,\n"
            "    FileReader, Fetch, Blob, URL.createObjectURL). System\n"
            "    fonts (Segoe UI, Roboto, ui-sans-serif, Consolas) are\n"
            "    requested via CSS font-family fallback chains — not\n"
            "    bundled or redistributed.\n"
            "\n"
            "Bundled into each Lively wallpaper zip (the page that renders\n"
            "the glow on your desktop):\n"
            "\n"
            "  • interact.js (drag / resize for placeable widgets) — MIT.\n"
            "    Full licence text shipped alongside the .js as\n"
            "    interact.LICENSE.txt in the same zip.\n"
            "    https://github.com/taye/interact.js\n"
            "\n"
            "Live web service queried at runtime (not bundled, only used\n"
            "by the optional Weather widget):\n"
            "\n"
            "  • Open-Meteo — free weather API, no account needed.\n"
            "    Data is CC-BY 4.0; the widget surfaces an 'Open-Meteo'\n"
            "    attribution in its footer when active.\n"
            "    https://open-meteo.com/\n"
            "\n"
            "Hosts the wallpaper plays inside (not bundled):\n"
            "\n"
            "  • Lively Wallpaper — GPL 3.0\n"
            "    https://github.com/rocksdanister/lively\n"
            "\n"
            "  • Wallpaper Engine (Steam) — proprietary, paid. The wallpaper\n"
            "    page targets Wallpaper Engine's Web wallpaper format too;\n"
            "    the installer can copy the three bundles straight into\n"
            "    Steam's wallpaper_engine\\projects\\myprojects folder when\n"
            "    detected.\n"
            "    https://www.wallpaperengine.io/\n"
            "\n"
            "  • SignalRGB — proprietary; this project uses their public plugin API.\n"
            "    https://signalrgb.com/  •  https://docs.signalrgb.com/\n"
            "\n"
            "Build tooling (not shipped, used only to produce the binary\n"
            "and release artifacts):\n"
            "\n"
            "  • GitHub CLI (releases), git, winget, Inno Setup (planned).\n"
        )

        text_frame = ttk.Frame(root)
        text_frame.pack(fill="both", expand=True, padx=16, pady=(4, 4))
        sb = ttk.Scrollbar(text_frame, orient="vertical")
        sb.pack(side="right", fill="y")
        text = tk.Text(text_frame, wrap="word", relief="flat",
                       background=root.cget("background"),
                       font=("Consolas", 9), yscrollcommand=sb.set)
        text.insert("1.0", oss_text)
        text.config(state="disabled")
        text.pack(side="left", fill="both", expand=True)
        sb.config(command=text.yview)

        btn_row = ttk.Frame(root)
        btn_row.pack(fill="x", padx=16, pady=12)
        ttk.Button(btn_row, text="Close", command=root.destroy).pack(side="right")

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
            items.append(pystray.MenuItem(
                f"⬆  Update available: {tag} — open release page",
                self._open_update_page))
            items.append(pystray.Menu.SEPARATOR)
        items.extend([
            pystray.MenuItem("Settings…",         self._open_settings, default=True),
            pystray.MenuItem("Build Wallpaper…",  self._open_builder),
            pystray.MenuItem("Widgets",           pystray.Menu(self._widget_menu_items)),
            pystray.MenuItem("Updates",           pystray.Menu(self._update_menu_items)),
            pystray.MenuItem("Reload config",     self._reload_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("About…",            self._open_about),
            pystray.MenuItem("Quit",              self._quit),
        ])
        return items

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
            pystray.MenuItem("Check for updates now", self._check_updates_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Enable update checks",  self._toggle_update_enabled,
                             checked=lambda _it, _e=enabled: _e),
            pystray.MenuItem("Allow beta versions",   self._toggle_allow_betas,
                             checked=lambda _it, _b=beta: _b),
            pystray.Menu.SEPARATOR,
        ]
        if avail:
            tag, _ = avail
            items.append(pystray.MenuItem(
                f"Latest: {tag} — open release page",
                self._open_update_page))
        elif err:
            short = (err[:48] + "…") if len(err) > 48 else err
            items.append(pystray.MenuItem(f"Last check failed: {short}",
                                          None, enabled=False))
        elif last_t > 0:
            ago = max(0, int(time.time() - last_t))
            if   ago < 60:   ago_s = f"{ago}s ago"
            elif ago < 3600: ago_s = f"{ago // 60}m ago"
            else:            ago_s = f"{ago // 3600}h ago"
            items.append(pystray.MenuItem(f"Up to date — last checked {ago_s}",
                                          None, enabled=False))
        else:
            items.append(pystray.MenuItem("Not yet checked",
                                          None, enabled=False))
        items.append(pystray.MenuItem(f"Installed: v{APP_VERSION}",
                                      None, enabled=False))
        return items

    def _check_updates_now(self, icon, item):
        self.update_checker.check_now()

    def _open_update_page(self, icon, item):
        avail = self.update_checker.available()
        url = avail[1] if avail else UPDATE_RELEASES_HTML
        try: webbrowser.open(url, new=2)
        except Exception as e: print(f"[tray] open release page failed: {e}")

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
                    f"Version {tag} is available. Open the tray menu to view "
                    f"the release page.",
                    "SignalRGB Wallpaper update",
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
                f"Screen {i + 1}",
                pystray.Menu(self._widget_screen_items_factory(i)),
            ))
        return items

    def _widget_screen_items_factory(self, screen: int):
        def items():
            with self.config_lock:
                s = self.config["screens"].get(str(screen), {})
                locked = bool(s.get("widgetsLocked", True))
                count  = len(s.get("widgets", []))
            menu = [
                pystray.MenuItem(
                    f"Edit widgets on this screen  ({'locked' if locked else 'EDIT MODE'})",
                    self._toggle_widgets_lock_factory(screen),
                    checked=lambda _it, _locked=locked: not _locked,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(f"Currently placed: {count}",
                                 None, enabled=False),
                pystray.Menu.SEPARATOR,
            ]
            # Generate one "Add <Label>" entry per registered widget type.
            # Order follows WIDGET_DEFAULTS insertion order so adding a new
            # type is one dict entry in this file + one registry entry in
            # the wallpaper page.
            for wtype, cfg in WIDGET_DEFAULTS.items():
                label = cfg.get("label", wtype.title())
                menu.append(pystray.MenuItem(f"Add {label}",
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
    config_lock = threading.Lock()

    bridge = BridgeRuntime(config, config_lock)
    bridge.start()

    tray = TrayApp(bridge, config, config_lock)
    tray.run()  # blocks on Win32 message pump


if __name__ == "__main__":
    main()
