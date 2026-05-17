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
import hashlib
import json
import mimetypes
import os
import struct
import sys
import threading
import time
import tkinter as tk
import urllib.parse
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, ttk

import pystray
from PIL import Image, ImageDraw

# ============================================================================
# Constants
# ============================================================================

UDP_HOST = "127.0.0.1"
UDP_PORT = 17320
WS_HOST  = "127.0.0.1"
WS_PORT  = 17320

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
}

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


def default_config() -> dict:
    return {
        "version": CONFIG_VERSION,
        "screenCount": 1,  # SignalRGB plugin polls /config and announces this many controllers
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

    def __init__(self, loop: asyncio.AbstractEventLoop, get_settings, get_screen_count):
        self.loop = loop
        self.get_settings = get_settings        # callable(screen:int)->dict
        self.get_screen_count = get_screen_count  # callable()->int (1..N_SCREENS)
        self.clients_by_screen: dict[int, set] = {}
        self._lock = asyncio.Lock()

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
                chunk = await reader.read(4096)
                if not chunk:
                    break
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

    def _get_settings(self, screen: int) -> dict:
        with self.config_lock:
            return dict(self.config["screens"].get(str(screen), DEFAULT_SCREEN_SETTINGS))

    def _get_screen_count(self) -> int:
        with self.config_lock:
            return int(self.config.get("screenCount", 1))

    def push_settings(self, screen: int, settings: dict):
        if self.broadcaster:
            self.broadcaster.push_settings_threadsafe(screen, settings)

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="bridge-asyncio").start()
        self._ready.wait()

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.broadcaster = Broadcaster(loop, self._get_settings, self._get_screen_count)
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
        self.root.geometry("540x520")
        self.root.minsize(500, 460)

        # Global section: how many screens to expose as SignalRGB devices.
        # Lives ABOVE the per-screen notebook because it's a one-knob global
        # setting, not a per-screen thing. The SignalRGB plugin polls the
        # bridge's /config endpoint and adjusts its announced controller
        # count to match this value.
        global_frame = ttk.LabelFrame(self.root, text="SignalRGB device count")
        global_frame.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(global_frame, text="Number of screens:").pack(side="left", padx=(8, 6), pady=8)
        sc_var = tk.IntVar(value=int(self.config.get("screenCount", 1)))
        self.global_vars["screenCount"] = sc_var
        sc_combo = ttk.Combobox(global_frame, textvariable=sc_var, values=[1, 2, 3],
                                state="readonly", width=4)
        sc_combo.pack(side="left", pady=8)
        ttk.Label(global_frame, text="(SignalRGB will show this many 'Desktop Wallpaper' devices)",
                  foreground="#666").pack(side="left", padx=(8, 0), pady=8)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        for n in range(N_SCREENS):
            tab = ttk.Frame(notebook)
            notebook.add(tab, text=f"Screen {n+1}")
            self.vars.append(self._build_tab(tab, n))

        btn_row = ttk.Frame(self.root)
        btn_row.pack(fill="x", padx=8, pady=8)
        # Close just dismisses the window. Save persists + pushes but keeps
        # the dialog open so the user can iterate / test / tweak the next
        # screen tab without re-opening.
        ttk.Button(btn_row, text="Close", command=self._on_close).pack(side="right")
        ttk.Button(btn_row, text="Save",  command=self._on_save).pack(side="right", padx=(0, 6))
        # Inline confirmation label, left-aligned. Empty until first save.
        self._saved_label = ttk.Label(btn_row, text="", foreground="#2a8a2a")
        self._saved_label.pack(side="left", padx=(2, 0))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # -- tab construction ---------------------------------------------------

    def _build_tab(self, parent: ttk.Frame, screen: int) -> dict[str, tk.Variable]:
        s = self.config["screens"][str(screen)]
        vars_: dict[str, tk.Variable] = {}

        row = 0
        # Background image picker
        ttk.Label(parent, text="Background image:").grid(row=row, column=0, sticky="w", padx=6, pady=(8, 2))
        bg_var = tk.StringVar(value=s["bgImage"])
        vars_["bgImage"] = bg_var
        entry = ttk.Entry(parent, textvariable=bg_var)
        entry.grid(row=row, column=1, sticky="we", padx=6, pady=(8, 2))
        ttk.Button(parent, text="Browse…", command=lambda v=bg_var: self._pick_image(v)).grid(row=row, column=2, padx=6, pady=(8, 2))
        row += 1

        # Image fit
        ttk.Label(parent, text="Image fit:").grid(row=row, column=0, sticky="w", padx=6, pady=2)
        fit_var = tk.StringVar(value=s["bgFit"] if s["bgFit"] in BG_FIT_CHOICES else "cover")
        vars_["bgFit"] = fit_var
        ttk.OptionMenu(parent, fit_var, fit_var.get(), *BG_FIT_CHOICES).grid(row=row, column=1, sticky="we", padx=6, pady=2)
        row += 1

        # Image dim
        ttk.Label(parent, text="Image dim (%):").grid(row=row, column=0, sticky="w", padx=6, pady=2)
        dim_var = tk.IntVar(value=int(s["bgDim"]))
        vars_["bgDim"] = dim_var
        self._slider(parent, dim_var, 0, 100, row, column=1)
        row += 1

        # Layout
        ttk.Label(parent, text="Glow layout:").grid(row=row, column=0, sticky="w", padx=6, pady=(12, 2))
        layout_var = tk.StringVar(value=s["barLayout"])
        vars_["barLayout"] = layout_var
        layout_labels = [label for _key, label in LAYOUT_CHOICES]
        label_to_key = {label: key for key, label in LAYOUT_CHOICES}
        current_label = next((label for key, label in LAYOUT_CHOICES if key == layout_var.get()), layout_labels[0])
        display_var = tk.StringVar(value=current_label)
        def _on_layout_change(label: str):
            layout_var.set(label_to_key.get(label, "lay-grid"))
        ttk.OptionMenu(parent, display_var, current_label, *layout_labels, command=_on_layout_change).grid(row=row, column=1, sticky="we", padx=6, pady=(12, 2))
        row += 1

        # Show glow toggle
        ttk.Label(parent, text="Enable glow:").grid(row=row, column=0, sticky="w", padx=6, pady=2)
        show_var = tk.BooleanVar(value=bool(s["showBars"]))
        vars_["showBars"] = show_var
        ttk.Checkbutton(parent, variable=show_var).grid(row=row, column=1, sticky="w", padx=6, pady=2)
        row += 1

        # Glow strength
        ttk.Label(parent, text="Glow strength:").grid(row=row, column=0, sticky="w", padx=6, pady=2)
        gs_var = tk.IntVar(value=int(s["glowStrength"]))
        vars_["glowStrength"] = gs_var
        self._slider(parent, gs_var, 0, 200, row, column=1)
        row += 1

        # Grid blur
        ttk.Label(parent, text="Grid blur (px):").grid(row=row, column=0, sticky="w", padx=6, pady=2)
        gb_var = tk.IntVar(value=int(s["gridBlur"]))
        vars_["gridBlur"] = gb_var
        self._slider(parent, gb_var, 0, 200, row, column=1)
        row += 1

        # Stripes blur
        ttk.Label(parent, text="Stripes blur (px):").grid(row=row, column=0, sticky="w", padx=6, pady=2)
        sb_var = tk.IntVar(value=int(s["stripesBlur"]))
        vars_["stripesBlur"] = sb_var
        self._slider(parent, sb_var, 0, 200, row, column=1)
        row += 1

        # Bar height (pills layout only)
        ttk.Label(parent, text="Bar height (% — pills):").grid(row=row, column=0, sticky="w", padx=6, pady=2)
        bh_var = tk.IntVar(value=int(s["barHeight"]))
        vars_["barHeight"] = bh_var
        self._slider(parent, bh_var, 10, 100, row, column=1)
        row += 1

        # Bar width (pills layout only)
        ttk.Label(parent, text="Bar width (‰ — pills):").grid(row=row, column=0, sticky="w", padx=6, pady=2)
        bw_var = tk.IntVar(value=int(s["barWidth"]))
        vars_["barWidth"] = bw_var
        self._slider(parent, bw_var, 1, 50, row, column=1)
        row += 1

        # Debug overlay
        ttk.Label(parent, text="Show debug overlay:").grid(row=row, column=0, sticky="w", padx=6, pady=(12, 2))
        ss_var = tk.BooleanVar(value=bool(s["showStatus"]))
        vars_["showStatus"] = ss_var
        ttk.Checkbutton(parent, variable=ss_var).grid(row=row, column=1, sticky="w", padx=6, pady=(12, 2))
        row += 1

        parent.columnconfigure(1, weight=1)
        return vars_

    def _slider(self, parent, var: tk.IntVar, lo: int, hi: int, row: int, column: int):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=column, sticky="we", padx=6, pady=2)
        scale = ttk.Scale(frame, from_=lo, to=hi, variable=var,
                          command=lambda v: var.set(int(float(v))))
        scale.pack(side="left", fill="x", expand=True)
        ttk.Label(frame, textvariable=var, width=4, anchor="e").pack(side="right", padx=(6, 0))

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

    def run(self):
        menu = pystray.Menu(
            pystray.MenuItem("Settings…",    self._open_settings,    default=True),
            pystray.MenuItem("Reload config", self._reload_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit",          self._quit),
        )
        self.icon = pystray.Icon(
            name="SignalRGBWallpaper",
            icon=build_tray_image(),
            title="SignalRGB Wallpaper Bridge",
            menu=menu,
        )
        self.icon.run()

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
