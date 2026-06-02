"""
OpenRGB Network-SDK *server* — the inverse of `openrgb_client.py`.
v1.6.2-beta. Where the client lets the bridge consume colours from
real OpenRGB devices, the server lets the bridge *expose itself* to
the OpenRGB GUI as a set of virtual devices. Users can then apply
OpenRGB's built-in effect engine (Rainbow Wave, Breathing, Audio
Visualizer, …) to the wallpaper without needing a SignalRGB
plugin in the loop.

Architecture:

  +-----------------+        TCP/6743          +--------------------+
  | OpenRGB GUI     | <----------------------> | Bridge SDK server  |
  | (effect engine) |   ORGB protocol packets  | (this module)      |
  +-----------------+                          +--------------------+
                                                       |
                                                       v
                                              +--------------------+
                                              | on_update_leds cb  |
                                              | → wallpaper feed   |
                                              +--------------------+

We expose ONE virtual device per screen. Each device carries a
single zone with a `matrix_map` shaped to the SignalRGB-grid
resolution that screen uses, so OpenRGB's effects (which can walk
matrices when they exist) produce spatially-coherent patterns
instead of treating the wallpaper as a flat LED strip.

Protocol reference: same as the client module —
    https://gitlab.com/CalcProgrammer1/OpenRGB/-/blob/master/Documentation/OpenRGBSDK.md

Wire format (server side mirrors the client):

  Each packet:
    char[4]   magic = "ORGB"
    uint32    device_index   (which controller the packet is for)
    uint32    packet_id
    uint32    data_length
    bytes     data_length bytes of payload

Packet IDs we *handle* on the server side:
  - REQUEST_CONTROLLER_COUNT     (0)  → reply uint32 count
  - REQUEST_CONTROLLER_DATA      (1)  → reply with full descriptor
  - REQUEST_PROTOCOL_VERSION     (40) → reply uint32 our_version
  - SET_CLIENT_NAME              (50) → record + ignore (informational)
  - RGBCONTROLLER_UPDATELEDS     (1050) → parse colours, fire callback
  - RGBCONTROLLER_UPDATEZONELEDS (1051) → same, scoped to one zone
  - RGBCONTROLLER_UPDATESINGLELED(1052) → same, single LED at index
  - RGBCONTROLLER_SETCUSTOMMODE  (1100) → no-op (we have no real modes)
  - RGBCONTROLLER_UPDATEMODE     (1101) → no-op (mode change)
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from typing import Callable


_MAGIC = b"ORGB"
_HEADER = struct.Struct("<4sIII")

# Packet IDs — receive side
NET_PACKET_ID_REQUEST_CONTROLLER_COUNT     = 0
NET_PACKET_ID_REQUEST_CONTROLLER_DATA      = 1
NET_PACKET_ID_REQUEST_PROTOCOL_VERSION     = 40
NET_PACKET_ID_SET_CLIENT_NAME              = 50
NET_PACKET_ID_RGBCONTROLLER_UPDATELEDS     = 1050
NET_PACKET_ID_RGBCONTROLLER_UPDATEZONELEDS = 1051
NET_PACKET_ID_RGBCONTROLLER_UPDATESINGLELED = 1052
NET_PACKET_ID_RGBCONTROLLER_SETCUSTOMMODE   = 1100
NET_PACKET_ID_RGBCONTROLLER_UPDATEMODE      = 1101

# We advertise protocol 4. That's enough to expose matrix_map (proto 1+)
# and segments per zone (proto 4+), and matches the client's
# PROTOCOL_VERSION_CLIENT — we keep one shared mental model.
PROTOCOL_VERSION_SERVER = 4

# OpenRGB device type enum — we report ourselves as DEVICE_TYPE_LEDSTRIP
# (4) so existing effects' "favourite device type" filters generally
# include us. The bigger reason to pick a strip type is that OpenRGB's
# effect plugin special-cases keyboards / mice, and we want the
# generic strip-with-matrix code path.
DEVICE_TYPE_LEDSTRIP = 4

# Default port. OpenRGB's GUI server lives on 6742; using 6743 sidesteps
# the inevitable conflict on machines where both run.
DEFAULT_PORT = 6743


# v1.6.2-beta hotfix4: built-in modes catalogue. Each entry advertises
# itself to the OpenRGB GUI as a selectable mode; the bridge-side
# effect engine renders the corresponding pattern at 30 Hz and pushes
# the result into the wallpaper via the same UpdateLEDs callback path
# Direct uses. Mode index = position in this list.
#
# Flag bits (subset of OpenRGB's MODE_FLAG_*):
MODE_FLAG_HAS_SPEED           = 0x01
MODE_FLAG_HAS_DIRECTION_LR    = 0x02
MODE_FLAG_HAS_DIRECTION_UD    = 0x04
MODE_FLAG_HAS_DIRECTION_HV    = 0x08
MODE_FLAG_HAS_BRIGHTNESS      = 0x10
MODE_FLAG_HAS_PER_LED_COLOR   = 0x20
MODE_FLAG_HAS_MODE_SPECIFIC_COLOR = 0x40
MODE_FLAG_HAS_RANDOM_COLOR    = 0x80
# color_mode enum (OpenRGB's ModeColors):
MODE_COLORS_NONE              = 0
MODE_COLORS_PER_LED           = 1
MODE_COLORS_MODE_SPECIFIC     = 2
MODE_COLORS_RANDOM            = 3

# Each entry: (name, flags, color_mode, default_speed, num_colors_min,
# num_colors_max). speed_min/max are fixed to 0..100 across the board
# so the GUI shows a normalised slider; the engine maps to a per-mode
# update rate. brightness_min/max are 0..100 too. The values column
# carries the mode "value" (an arbitrary device-defined identifier;
# we use the catalogue index since we have no real hardware modes).
BUILTIN_MODES = [
    # Direct — what we shipped in v1.6.2-beta hotfix3. Accepts UpdateLEDs
    # writes verbatim, no engine work. Always index 0 so existing
    # documentation that refers to "the Direct mode" stays correct.
    ("Direct",       MODE_FLAG_HAS_PER_LED_COLOR,                          MODE_COLORS_PER_LED, 50, 0, 0),
    # Static — one solid colour across every LED. num_colors = 1.
    ("Static",       MODE_FLAG_HAS_MODE_SPECIFIC_COLOR,                    MODE_COLORS_MODE_SPECIFIC, 50, 1, 1),
    # Breathing — single colour, brightness eased via sin(t).
    ("Breathing",    MODE_FLAG_HAS_SPEED | MODE_FLAG_HAS_BRIGHTNESS
                     | MODE_FLAG_HAS_MODE_SPECIFIC_COLOR,                  MODE_COLORS_MODE_SPECIFIC, 50, 1, 1),
    # Rainbow — hue cycles across the whole device uniformly over time.
    ("Rainbow",      MODE_FLAG_HAS_SPEED | MODE_FLAG_HAS_BRIGHTNESS,       MODE_COLORS_NONE,    50, 0, 0),
    # Rainbow Wave — hue offset varies per LED position so colours sweep
    # across the strip / matrix. Single direction (LR) on a linear zone.
    ("Rainbow Wave", MODE_FLAG_HAS_SPEED | MODE_FLAG_HAS_BRIGHTNESS
                     | MODE_FLAG_HAS_DIRECTION_LR,                         MODE_COLORS_NONE,    50, 0, 0),
    # Color Wave — same shape as Rainbow Wave but uses a user-picked
    # base colour (interpolated across hues centred on the colour).
    ("Color Wave",   MODE_FLAG_HAS_SPEED | MODE_FLAG_HAS_BRIGHTNESS
                     | MODE_FLAG_HAS_MODE_SPECIFIC_COLOR
                     | MODE_FLAG_HAS_DIRECTION_LR,                         MODE_COLORS_MODE_SPECIFIC, 50, 1, 1),
]


# ─────────────────────────────────────────────────────────────────────
# Device descriptor — what we hand back when a client requests
# REQUEST_CONTROLLER_DATA. One device per screen; the matrix carries
# the SignalRGB-grid topology so effects produce spatially-coherent
# output instead of treating the LEDs as a flat strip.
# ─────────────────────────────────────────────────────────────────────


class VirtualDevice:
    """One virtual device exposed to OpenRGB. Carries the SignalRGB grid
    dimensions (width × height); LED count is width*height. Active
    mode + per-mode parameters (speed / brightness / colour) are
    tracked here so the bridge-side effect engine can read them on
    every tick.

    Mode index 0 is always Direct (UPDATELEDS writes only — no engine
    work). Other indices map to BUILTIN_MODES; the engine renders
    those at 30 Hz and pushes through the UpdateLEDs callback."""

    __slots__ = ("name", "width", "height", "screen_idx",
                 "mode_index", "speed", "brightness", "color",
                 "direction")

    def __init__(self, screen_idx: int, name: str,
                 width: int, height: int):
        self.screen_idx = int(screen_idx)
        self.name = str(name)
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        # Effect-engine state. Defaults match Direct so a freshly
        # connected GUI without an explicit mode pick stays in
        # Direct (the engine skips Direct entirely).
        self.mode_index = 0
        self.speed = 50
        self.brightness = 100
        self.color = (255, 255, 255)
        self.direction = 0

    @property
    def led_count(self) -> int:
        return self.width * self.height


def _pack_string(s: str) -> bytes:
    """OpenRGB strings are length-prefixed UTF-8 INCLUDING the
    trailing null byte. The length is uint16-LE."""
    body = s.encode("utf-8") + b"\x00"
    return struct.pack("<H", len(body)) + body


def build_controller_data(dev: VirtualDevice, version: int) -> bytes:
    """Serialise `dev` into the REQUEST_CONTROLLER_DATA reply format
    `_parse_controller_data` in openrgb_client.py parses on the other
    side. Same byte layout that real OpenRGB devices emit.

    Layout (matching the parser exactly):
        uint32  data_size (we patch in at the end — total len incl self)
        uint32  device_type
        string  name
        string  vendor              (proto 1+)
        string  description
        string  version
        string  serial
        string  location
        uint16  num_modes (= 1)
        int32   active_mode (= 0, "Direct")
        # One required "Direct" mode — OpenRGB's GUI dereferences
        # modes[active_mode] unconditionally and crashes on
        # num_modes=0. Mode body is 9 × uint32 (proto 0-2) or
        # 12 × uint32 (proto 3+) followed by uint16 num_colors (= 0).
        uint16  num_zones (= 1)
        per zone:
            string  zone_name
            uint32  zone_type        (0 = ZONE_TYPE_SINGLE,
                                       1 = LINEAR, 2 = MATRIX)
            uint32  leds_min
            uint32  leds_max
            uint32  leds_count
            uint16  matrix_size      (= 4*W*H + 8 if matrix, else 0)
            uint32  matrix_height    (only when matrix_size > 0)
            uint32  matrix_width
            uint32[H*W]  matrix      (LED index per cell, row-major)
            uint16  num_segments     (proto 4+, = 0)
        uint16  num_leds
        per LED:
            string  led_name
            uint32  led_value        (we write 0 — raw register, unused)
        uint16  num_colors           (= num_leds; current colour array)
        uint32[num_leds]  colors     (BGR0 packed; we send all-zero)
    """
    led_count = dev.led_count
    parts: list[bytes] = []
    # device_type (uint32). data_size is patched at the end.
    parts.append(struct.pack("<I", DEVICE_TYPE_LEDSTRIP))
    parts.append(_pack_string(dev.name))
    if version >= 1:
        parts.append(_pack_string("SignalRGB Wallpaper Bridge"))   # vendor
    parts.append(_pack_string("Virtual wallpaper-glow device"))    # description
    parts.append(_pack_string("1.6.2-beta"))                       # version
    parts.append(_pack_string(""))                                 # serial
    parts.append(_pack_string("bridge"))                           # location
    # v1.6.2-beta hotfix4: ship the full BUILTIN_MODES catalogue —
    # Direct + Static + Breathing + Rainbow + Rainbow Wave + Color
    # Wave. Mode index = position in the catalogue. The bridge-side
    # effect engine renders non-Direct modes at 30 Hz and pushes the
    # result through the same UpdateLEDs callback Direct uses.
    parts.append(struct.pack("<H", len(BUILTIN_MODES)))   # num_modes
    parts.append(struct.pack("<i", 0))                    # active_mode = 0 (Direct)
    for i, (mname, mflags, mcolor_mode, mspeed,
            num_colors_min, num_colors_max) in enumerate(BUILTIN_MODES):
        parts.append(_pack_string(mname))
        # speed / brightness range fixed to 0..100 across the board so
        # the GUI slider is normalised; the engine maps a raw value
        # back to per-mode update rate / amplitude.
        if version >= 3:
            parts.append(struct.pack("<12I",
                i,                                  # value (= mode index)
                mflags,                             # flags
                0, 100,                             # speed_min, speed_max
                0, 100,                             # brightness_min, brightness_max
                num_colors_min, num_colors_max,     # colors_min, colors_max
                mspeed,                             # speed (current)
                100,                                # brightness
                0,                                  # direction (LR=0)
                mcolor_mode,                        # color_mode
            ))
        else:
            parts.append(struct.pack("<9I",
                i, mflags,
                0, 100,
                num_colors_min, num_colors_max,
                mspeed,
                0,
                mcolor_mode,
            ))
        # v1.6.2-beta hotfix5: pre-seed colours_min default colours.
        # Previous version emitted num_colors = 0 across the board.
        # That parsed cleanly when colors_min = 0 (Direct / Rainbow /
        # Rainbow Wave) but crashed the OpenRGB GUI on every mode
        # where colors_min >= 1 (Static / Breathing / Color Wave) —
        # the GUI dereferences mode.colors[0] for the picker preview
        # without a bounds check. Seed with white per slot so the
        # picker shows something on first display; the user's pick
        # comes back via UPDATEMODE and the engine takes over.
        parts.append(struct.pack("<H", num_colors_min))
        for _ in range(num_colors_min):
            # Wire is BGR0 packed as LE-uint32: bytes (R, G, B, 0).
            parts.append(b"\xff\xff\xff\x00")

    # v1.6.2-beta hotfix2: single LINEAR zone instead of MATRIX. The
    # original matrix descriptor parsed cleanly with our own
    # openrgb_client.py but OpenRGB's GUI rejected the zone entirely
    # (Zone dropdown stayed empty in the GUI → no LEDs, no apply).
    # `matrix_size` encoding turned out to differ between server
    # implementations: some treat it as the byte size of the matrix
    # block that follows (8 + 4*W*H), others as a flag (1 if present)
    # or the cell count. Until we identify which OpenRGB's parser
    # expects, ship a flat strip — Direct-mode writes still flow,
    # spatially-aware effects (Rainbow Wave) just iterate linearly
    # across the strip instead of walking rows. Matrix support comes
    # back in a follow-up once the byte layout is pinned down.
    parts.append(struct.pack("<H", 1))                # num_zones
    parts.append(_pack_string("Wallpaper"))           # zone_name
    parts.append(struct.pack("<I", 1))                # zone_type (LINEAR)
    parts.append(struct.pack("<I", led_count))        # leds_min
    parts.append(struct.pack("<I", led_count))        # leds_max
    parts.append(struct.pack("<I", led_count))        # leds_count
    parts.append(struct.pack("<H", 0))                # matrix_size = 0 (no matrix)
    # Segments (proto 4+) — none.
    if version >= 4:
        parts.append(struct.pack("<H", 0))            # num_segments

    # Per-LED descriptors.
    parts.append(struct.pack("<H", led_count))         # num_leds
    for i in range(led_count):
        parts.append(_pack_string(f"LED {i}"))
        parts.append(struct.pack("<I", 0))             # led_value (unused)

    # Current colours — all-zero on enumerate. Real updates come from
    # UpdateLEDs writes; reading back is supported because the client
    # path uses it as a "get_colors" channel.
    parts.append(struct.pack("<H", led_count))
    parts.append(b"\x00\x00\x00\x00" * led_count)

    body = b"".join(parts)
    # Prepend data_size (uint32) — includes itself + body, matching the
    # `_data_size, device_type = struct.unpack_from("<II", data, pos)`
    # the client parser reads first.
    return struct.pack("<I", len(body) + 4) + body


# ─────────────────────────────────────────────────────────────────────
# Server
# ─────────────────────────────────────────────────────────────────────


# Callback contract: bridge passes a function in that we fire on every
# RGBCONTROLLER_UPDATELEDS (or zone / single variants) we receive. The
# bridge maps the colour array onto the wallpaper grid for that screen.
UpdateCallback = Callable[[int, list[tuple[int, int, int]]], None]


class OpenRgbSdkServer:
    """Thread-per-client TCP server speaking the OpenRGB SDK protocol.

    Lifecycle:
        srv = OpenRgbSdkServer(devices, on_update_leds, port=6743)
        srv.start()
        ...
        srv.stop()

    Multi-client safe: each connection gets its own reader thread + an
    optional client_name string. UpdateLEDs writes from any client fire
    the same callback — last-write-wins semantics on the wallpaper.

    Devices are mutable: the bridge can call `replace_devices(new_list)`
    when the user reconfigures grid resolution. New clients see the
    new descriptor; existing clients are advised to reconnect (we drop
    them to avoid serving a stale matrix size mid-session)."""

    def __init__(self, devices: list[VirtualDevice],
                 on_update_leds: UpdateCallback,
                 host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        self._devices = list(devices)
        self._on_update_leds = on_update_leds
        self.host = host
        self.port = port
        self._listen_sock: socket.socket | None = None
        self._stop = threading.Event()
        self._accept_thread: threading.Thread | None = None
        # Active client sockets, kept so we can close them on stop /
        # device-list replace. dict[id(socket) -> (sock, client_name)].
        self._clients: dict[int, tuple[socket.socket, str]] = {}
        self._clients_lock = threading.Lock()
        # Stats surfaced via /openrgb-sdk/status.
        self.client_count_now = 0
        self.last_update_ts = 0.0
        self.last_error = ""
        self.running = False

    # ── lifecycle ──────────────────────────────────────────────────

    def start(self) -> bool:
        if self.running:
            return True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen(8)
            s.settimeout(1.0)   # so the accept loop can poll _stop
            self._listen_sock = s
        except OSError as e:
            self.last_error = f"bind {self.host}:{self.port} failed: {e}"
            print(f"[openrgb-sdk] {self.last_error}")
            return False
        self._stop.clear()
        self.running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, daemon=True,
            name="openrgb-sdk-accept")
        self._accept_thread.start()
        print(f"[openrgb-sdk] listening on {self.host}:{self.port} "
              f"({len(self._devices)} virtual device(s))")
        return True

    def stop(self) -> None:
        if not self.running:
            return
        self._stop.set()
        # Close listen + every client socket — wakes blocked recvs.
        try:
            if self._listen_sock is not None:
                self._listen_sock.close()
        except Exception:
            pass
        self._listen_sock = None
        with self._clients_lock:
            for sock, _name in list(self._clients.values()):
                try: sock.close()
                except Exception: pass
            self._clients.clear()
        self.running = False
        self.client_count_now = 0
        print("[openrgb-sdk] stopped")

    def replace_devices(self, devices: list[VirtualDevice]) -> None:
        """Swap the device list (e.g., user added a screen or changed
        grid resolution). All connected clients are dropped — they
        cached the old descriptor + matrix shape so continuing to
        serve them would silently desync. They'll reconnect and
        re-enumerate against the fresh list."""
        self._devices = list(devices)
        with self._clients_lock:
            for sock, _name in list(self._clients.values()):
                try: sock.close()
                except Exception: pass
            self._clients.clear()
        self.client_count_now = 0
        print(f"[openrgb-sdk] device list replaced "
              f"({len(self._devices)} device(s)) — clients dropped")

    # ── status (surfaced via /openrgb-sdk/status) ──────────────────

    def status(self) -> dict:
        return {
            "running":      self.running,
            "host":         self.host,
            "port":         self.port,
            "deviceCount":  len(self._devices),
            "devices":      [{"name": d.name,
                              "ledCount": d.led_count,
                              "matrix": [d.width, d.height]}
                             for d in self._devices],
            "clientCount":  self.client_count_now,
            "lastUpdateMs": int(self.last_update_ts * 1000),
            "lastError":    self.last_error,
        }

    # ── accept loop ────────────────────────────────────────────────

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            if self._listen_sock is None:
                break
            try:
                client_sock, addr = self._listen_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                # Listen sock got closed → stop() in flight, exit cleanly.
                break
            client_sock.settimeout(None)
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._clients_lock:
                self._clients[id(client_sock)] = (client_sock, "")
                self.client_count_now = len(self._clients)
            print(f"[openrgb-sdk] client connected: {addr}")
            t = threading.Thread(
                target=self._client_loop, args=(client_sock, addr),
                daemon=True,
                name=f"openrgb-sdk-client-{addr[1]}")
            t.start()
        print("[openrgb-sdk] accept loop exited")

    # ── per-client reader ──────────────────────────────────────────

    def _client_loop(self, sock: socket.socket, addr) -> None:
        try:
            while not self._stop.is_set():
                header = self._recv_exact(sock, _HEADER.size)
                if header is None:
                    break
                magic, dev_idx, packet_id, data_len = _HEADER.unpack(header)
                if magic != _MAGIC:
                    print(f"[openrgb-sdk] {addr}: bad magic {magic!r}, "
                          f"dropping")
                    break
                data = self._recv_exact(sock, data_len) if data_len else b""
                if data is None:
                    break
                self._dispatch(sock, dev_idx, packet_id, data)
        except OSError as e:
            print(f"[openrgb-sdk] {addr}: socket error {e}")
        except Exception as e:
            print(f"[openrgb-sdk] {addr}: dispatch failed {e}")
        finally:
            with self._clients_lock:
                self._clients.pop(id(sock), None)
                self.client_count_now = len(self._clients)
            try: sock.close()
            except Exception: pass
            print(f"[openrgb-sdk] client disconnected: {addr}")

    def _recv_exact(self, sock: socket.socket, n: int) -> bytes | None:
        """Read exactly n bytes from sock. Returns None on clean close
        or stop request — the caller exits its loop."""
        buf = bytearray()
        while len(buf) < n:
            if self._stop.is_set():
                return None
            try:
                chunk = sock.recv(n - len(buf))
            except OSError:
                return None
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def _send(self, sock: socket.socket, dev_idx: int,
              packet_id: int, payload: bytes = b"") -> bool:
        try:
            sock.sendall(_HEADER.pack(_MAGIC, dev_idx, packet_id,
                                       len(payload)))
            if payload:
                sock.sendall(payload)
            return True
        except OSError:
            return False

    # ── dispatch ───────────────────────────────────────────────────

    def _dispatch(self, sock: socket.socket, dev_idx: int,
                  packet_id: int, data: bytes) -> None:
        # The few packet IDs we care about. Everything else gets a
        # silent ignore — keeps us forward-compatible with new packet
        # types future OpenRGB clients might fire.
        if packet_id == NET_PACKET_ID_SET_CLIENT_NAME:
            # Null-terminated UTF-8.
            name = data.rstrip(b"\x00").decode("utf-8", "replace")
            with self._clients_lock:
                if id(sock) in self._clients:
                    s, _ = self._clients[id(sock)]
                    self._clients[id(sock)] = (s, name)
            print(f"[openrgb-sdk] client name: {name!r}")

        elif packet_id == NET_PACKET_ID_REQUEST_PROTOCOL_VERSION:
            # Client claims a version in the payload (uint32); we reply
            # with OUR max. The client takes min(theirs, ours).
            client_claim = struct.unpack("<I", data[:4])[0] \
                if len(data) >= 4 else 0
            self._send(sock, 0, NET_PACKET_ID_REQUEST_PROTOCOL_VERSION,
                       struct.pack("<I", PROTOCOL_VERSION_SERVER))
            print(f"[openrgb-sdk] proto handshake: client claimed "
                  f"{client_claim}, we offer {PROTOCOL_VERSION_SERVER}")

        elif packet_id == NET_PACKET_ID_REQUEST_CONTROLLER_COUNT:
            self._send(sock, 0, NET_PACKET_ID_REQUEST_CONTROLLER_COUNT,
                       struct.pack("<I", len(self._devices)))

        elif packet_id == NET_PACKET_ID_REQUEST_CONTROLLER_DATA:
            if dev_idx >= len(self._devices):
                return
            # Client sends its negotiated protocol version in payload.
            version = struct.unpack("<I", data[:4])[0] \
                if len(data) >= 4 else PROTOCOL_VERSION_SERVER
            version = min(version, PROTOCOL_VERSION_SERVER)
            blob = build_controller_data(self._devices[dev_idx], version)
            self._send(sock, dev_idx,
                       NET_PACKET_ID_REQUEST_CONTROLLER_DATA, blob)

        elif packet_id in (NET_PACKET_ID_RGBCONTROLLER_UPDATELEDS,
                            NET_PACKET_ID_RGBCONTROLLER_UPDATEZONELEDS,
                            NET_PACKET_ID_RGBCONTROLLER_UPDATESINGLELED):
            self._handle_update(dev_idx, packet_id, data)

        elif packet_id in (NET_PACKET_ID_RGBCONTROLLER_UPDATEMODE,
                            NET_PACKET_ID_RGBCONTROLLER_SETCUSTOMMODE):
            self._handle_mode_update(dev_idx, data)

        # Other packet IDs → silent ignore. Forward-compatible with new
        # packet types future OpenRGB clients might fire.

    # ── UPDATEMODE ────────────────────────────────────────────────

    def _handle_mode_update(self, dev_idx: int, data: bytes) -> None:
        """Parse RGBCONTROLLER_UPDATEMODE payload + update the device's
        active mode + speed + brightness + colour. Engine picks up the
        new state on its next 30-Hz tick.

        Payload layout (matching RGBController_LoadNetwork):
            uint32  data_size
            uint32  mode_index
            string  mode_name           (re-sent for sanity, ignored)
            mode body — 12 × uint32 (proto 3+) or 9 × uint32 (proto 0-2)
            uint16  num_colors
            uint32[num_colors]  colours (BGR0)
        """
        if dev_idx >= len(self._devices):
            return
        dev = self._devices[dev_idx]
        try:
            if len(data) < 8:
                return
            mode_idx = struct.unpack_from("<I", data, 4)[0]
            pos = 8
            # Skip the mode_name string. _parse_update_mode_string walks
            # uint16 length + body — same shape as descriptor strings.
            if pos + 2 > len(data):
                return
            name_len = struct.unpack_from("<H", data, pos)[0]
            pos += 2 + name_len
            # Mode body: 12 × uint32 on proto 3+, 9 × uint32 on proto 0-2.
            # We can't tell from the packet alone which version the
            # client used, but the GUI always honours our handshake, so
            # we read 12 fields and tolerate the 9-field case via a
            # bounds check.
            if pos + 4 * 12 > len(data):
                if pos + 4 * 9 > len(data):
                    return
                fields = struct.unpack_from("<9I", data, pos)
                pos += 4 * 9
                # 9-field layout: value, flags, speed_min, speed_max,
                # colors_min, colors_max, speed, direction, color_mode
                _value, _flags, _smin, _smax, _cmin, _cmax, speed, direction, _cmode = fields
                brightness = 100
            else:
                fields = struct.unpack_from("<12I", data, pos)
                pos += 4 * 12
                # 12-field layout: value, flags, speed_min, speed_max,
                # brightness_min, brightness_max, colors_min, colors_max,
                # speed, brightness, direction, color_mode
                (_value, _flags, _smin, _smax, _bmin, _bmax,
                 _cmin, _cmax, speed, brightness, direction, _cmode) = fields
            # num_colors uint16 then colours[]. Use the first colour as
            # the mode's "Mode-Specific" colour pick. Static / Breathing
            # / Color Wave all read this.
            if pos + 2 <= len(data):
                ncols = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                if ncols > 0 and pos + 4 <= len(data):
                    r, g, b, _ = (data[pos], data[pos + 1],
                                   data[pos + 2], data[pos + 3])
                    dev.color = (r, g, b)
            # Commit.
            dev.mode_index = max(0, min(len(BUILTIN_MODES) - 1, int(mode_idx)))
            dev.speed = max(0, min(100, int(speed)))
            dev.brightness = max(0, min(100, int(brightness)))
            dev.direction = int(direction) & 0xff
            print(f"[openrgb-sdk] {dev.name} → mode "
                  f"{BUILTIN_MODES[dev.mode_index][0]!r} "
                  f"(speed={dev.speed}, bright={dev.brightness}, "
                  f"col={dev.color})")
        except (struct.error, IndexError, ValueError) as e:
            self.last_error = f"update_mode parse: {e}"

    # ── UPDATELEDS family ─────────────────────────────────────────

    def _handle_update(self, dev_idx: int, packet_id: int,
                       data: bytes) -> None:
        if dev_idx >= len(self._devices):
            return
        dev = self._devices[dev_idx]
        try:
            if packet_id == NET_PACKET_ID_RGBCONTROLLER_UPDATELEDS:
                colors = _parse_update_leds(data)
            elif packet_id == NET_PACKET_ID_RGBCONTROLLER_UPDATEZONELEDS:
                colors = _parse_update_zone_leds(data, dev.led_count)
            elif packet_id == NET_PACKET_ID_RGBCONTROLLER_UPDATESINGLELED:
                # Single LED update: payload = uint32 led_index + uint32 BGRA.
                # We treat it as a colour delta — the bridge keeps its
                # last-known full grid + patches in this one cell. For
                # the v1.6.2-beta MVP we just punt: ignore single-LED
                # writes. Effects don't use this path.
                return
            else:
                return
        except (struct.error, ValueError) as e:
            self.last_error = f"update parse: {e}"
            return
        if not colors:
            return
        self.last_update_ts = time.time()
        # Fire the callback OUTSIDE any lock. The bridge's
        # implementation hops to the asyncio loop via call_soon_thread-
        # safe, so this returns fast.
        try:
            self._on_update_leds(dev.screen_idx, colors)
        except Exception as e:
            print(f"[openrgb-sdk] callback failed: {e}")


# ─────────────────────────────────────────────────────────────────────
# Update-LEDs payload parsers
# ─────────────────────────────────────────────────────────────────────


def _parse_update_leds(data: bytes) -> list[tuple[int, int, int]]:
    """RGBCONTROLLER_UPDATELEDS payload:
        uint32  data_size  (includes itself)
        uint16  num_colors
        uint32[num_colors]  BGR0-packed colours
    """
    if len(data) < 6:
        raise ValueError("update_leds payload too short")
    _data_size, num_colors = struct.unpack_from("<IH", data, 0)
    pos = 6
    if pos + 4 * num_colors > len(data):
        raise ValueError("update_leds truncated colour array")
    colors: list[tuple[int, int, int]] = []
    for _ in range(num_colors):
        # On the wire each colour is the LE-uint32 packed as R G B 0
        # (matching the client's push_color encoding).
        r, g, b, _ = data[pos], data[pos + 1], data[pos + 2], data[pos + 3]
        colors.append((r, g, b))
        pos += 4
    return colors


def _parse_update_zone_leds(data: bytes,
                             total_led_count: int) -> list[tuple[int, int, int]]:
    """RGBCONTROLLER_UPDATEZONELEDS payload:
        uint32  data_size
        uint32  zone_index    (we only expose zone 0, so anything
                               else means the client lost track)
        uint16  num_colors
        uint32[num_colors]  BGR0 colours

    Since our device has exactly one zone covering all LEDs, a
    zone-update for zone 0 is functionally identical to a full
    UPDATELEDS. We treat any other zone as a no-op (return [])."""
    if len(data) < 10:
        raise ValueError("update_zone_leds payload too short")
    _data_size, zone_idx, num_colors = struct.unpack_from("<IIH", data, 0)
    if zone_idx != 0:
        return []
    pos = 10
    if pos + 4 * num_colors > len(data):
        raise ValueError("update_zone_leds truncated colour array")
    colors: list[tuple[int, int, int]] = []
    for _ in range(num_colors):
        r, g, b, _ = data[pos], data[pos + 1], data[pos + 2], data[pos + 3]
        colors.append((r, g, b))
        pos += 4
    return colors
