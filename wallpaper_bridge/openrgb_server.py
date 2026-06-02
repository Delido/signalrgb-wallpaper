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


# ─────────────────────────────────────────────────────────────────────
# Device descriptor — what we hand back when a client requests
# REQUEST_CONTROLLER_DATA. One device per screen; the matrix carries
# the SignalRGB-grid topology so effects produce spatially-coherent
# output instead of treating the LEDs as a flat strip.
# ─────────────────────────────────────────────────────────────────────


class VirtualDevice:
    """One virtual device exposed to OpenRGB. Carries the SignalRGB grid
    dimensions (width × height) so we can emit a matrix_map; LED count
    is width*height. Reference is held by the server; the bridge
    mutates `width` / `height` when the user reconfigures grid size."""

    __slots__ = ("name", "width", "height", "screen_idx")

    def __init__(self, screen_idx: int, name: str,
                 width: int, height: int):
        self.screen_idx = int(screen_idx)
        self.name = str(name)
        self.width = max(1, int(width))
        self.height = max(1, int(height))

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
    # v1.6.2-beta hotfix: OpenRGB's GUI assumes every device exposes
    # at least one mode (typically "Direct"). num_modes=0 segfaulted
    # the GUI on connect because the mode selector + the effect plugin
    # both dereference modes[active_mode] unconditionally. Ship a
    # single "Direct" mode with HAS_PER_LED_COLOR set so UPDATELEDS
    # writes are the canonical flow.
    parts.append(struct.pack("<H", 1))   # num_modes = 1
    parts.append(struct.pack("<i", 0))   # active_mode = 0 (Direct)
    parts.append(_pack_string("Direct"))
    # Mode body layout: 9 × uint32 (proto 0-2) or 12 × uint32 (proto 3+),
    # then uint16 num_colors + colour array. Field order matches the
    # client parser's offset table.
    #   MODE_FLAG_HAS_PER_LED_COLOR = 0x01
    #   MODE_COLORS_PER_LED         = 4
    if version >= 3:
        parts.append(struct.pack("<12I",
            0,        # value
            0x01,     # flags = MODE_FLAG_HAS_PER_LED_COLOR
            0, 0,     # speed_min, speed_max
            0, 0,     # brightness_min, brightness_max
            0, 0,     # colors_min, colors_max
            0,        # speed
            0,        # brightness
            0,        # direction
            4,        # color_mode = MODE_COLORS_PER_LED
        ))
    else:
        parts.append(struct.pack("<9I",
            0,        # value
            0x01,     # flags = MODE_FLAG_HAS_PER_LED_COLOR
            0, 0,     # speed_min, speed_max
            0, 0,     # colors_min, colors_max
            0,        # speed
            0,        # direction
            4,        # color_mode = MODE_COLORS_PER_LED
        ))
    parts.append(struct.pack("<H", 0))   # num_colors (Direct has none)

    # Single zone, matrix layout. zone_type 2 == ZONE_TYPE_MATRIX.
    parts.append(struct.pack("<H", 1))                # num_zones
    parts.append(_pack_string("Wallpaper grid"))      # zone_name
    parts.append(struct.pack("<I", 2))                # zone_type (matrix)
    parts.append(struct.pack("<I", led_count))        # leds_min
    parts.append(struct.pack("<I", led_count))        # leds_max
    parts.append(struct.pack("<I", led_count))        # leds_count

    # matrix_size is the size of the matrix block that follows: 8 bytes
    # for height+width plus 4 bytes per cell. The client's parser reads
    # `matrix_size` as a uint16 — clamp safely; for typical 32×16 grids
    # this is 8 + 4*512 = 2056 which is well under 65535.
    matrix_block_size = 8 + 4 * dev.width * dev.height
    parts.append(struct.pack("<H", min(matrix_block_size, 0xFFFF)))
    parts.append(struct.pack("<II", dev.height, dev.width))
    # Row-major LED indices: (row*width + col).
    for r in range(dev.height):
        for c in range(dev.width):
            parts.append(struct.pack("<I", r * dev.width + c))
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

        # UpdateMode / SetCustomMode / others → no-op. We don't have
        # device-side modes; the GUI sees a Direct device + writes
        # colours via UpdateLEDs. Silent ignore is fine.

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
