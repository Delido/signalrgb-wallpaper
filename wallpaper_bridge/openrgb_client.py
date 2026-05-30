"""
Minimal OpenRGB Network-SDK client for the bridge's OpenRGB-output
channel (v1.4-beta). Connects to OpenRGB's TCP server (default
localhost:6742), enumerates controllers, and pushes per-device LED
colour arrays.

We speak the binary protocol directly instead of pulling in
`openrgb-python` for two reasons:
  • openrgb-python is GPL-3.0 — we ship under MIT, can't bundle.
  • Our needs are tiny (handshake, enumerate, push colours), so a
    300-line self-contained module is preferable to a heavy dep that
    drags in click + every protocol-version compatibility shim.

The OpenRGB SDK uses 16-byte little-endian packet headers:
    char[4]   magic = "ORGB"
    uint32    device_index
    uint32    packet_id
    uint32    data_length
followed by `data_length` bytes of payload.

This client only handles enumeration + UPDATELEDS for now. Adding
zone-level / single-LED updates later means adding the corresponding
packet IDs to the dispatch.

Protocol reference:
    https://gitlab.com/CalcProgrammer1/OpenRGB/-/blob/master/Documentation/OpenRGBSDK.md
"""

from __future__ import annotations

import socket
import struct
import threading


_MAGIC = b"ORGB"
_HEADER = struct.Struct("<4sIII")

# Packet IDs we use. The full list is in the protocol doc; everything
# we don't dispatch is silently ignored.
REQUEST_CONTROLLER_COUNT     = 0
REQUEST_CONTROLLER_DATA      = 1
REQUEST_PROTOCOL_VERSION     = 40
SET_CLIENT_NAME              = 50
RGBCONTROLLER_UPDATELEDS     = 1050

# Highest protocol version we know how to parse. OpenRGB negotiates
# down — server replies with min(client, server) — so claiming 4
# while the server speaks 3 lands us on 3.
PROTOCOL_VERSION_CLIENT = 4


class OpenRGBError(Exception):
    pass


class OpenRGBClient:
    """Thread-safe client. All public methods serialise on a single
    socket lock so concurrent `push_*` calls from the broadcaster
    thread + the Configurator's status-poll path don't interleave
    half-packets on the wire."""

    def __init__(self,
                 host: str = "127.0.0.1",
                 port: int = 6742,
                 client_name: str = "SignalRGB Wallpaper Bridge",
                 timeout: float = 2.0):
        self.host = host
        self.port = port
        self.client_name = client_name
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        # Server's negotiated protocol version (post-handshake).
        self.protocol_version: int = 0
        # [{id, name, led_count, type}, …] populated by enumerate().
        self.devices: list[dict] = []

    # ── lifecycle ──────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Open the TCP socket, run the handshake, enumerate devices.
        Returns True on success, False on any failure (including
        OpenRGB not running). Safe to call repeatedly — closes any
        prior socket first."""
        self.disconnect()
        try:
            s = socket.create_connection(
                (self.host, self.port), timeout=self.timeout)
            s.settimeout(self.timeout)
            self._sock = s
            self._handshake()
            self._enumerate()
            return True
        except (OSError, OpenRGBError, struct.error) as e:
            print(f"[openrgb] connect failed: {e}")
            self.disconnect()
            return False

    def disconnect(self) -> None:
        with self._lock:
            if self._sock is not None:
                try: self._sock.close()
                except Exception: pass
                self._sock = None
            self.protocol_version = 0
            self.devices = []

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # ── transport helpers ──────────────────────────────────────────────

    def _send(self, dev_id: int, packet_id: int, data: bytes = b"") -> None:
        if self._sock is None:
            raise OpenRGBError("not connected")
        header = _HEADER.pack(_MAGIC, dev_id, packet_id, len(data))
        self._sock.sendall(header + data)

    def _recv_exact(self, n: int) -> bytes:
        if self._sock is None:
            raise OpenRGBError("not connected")
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise OpenRGBError("server closed the connection mid-packet")
            buf.extend(chunk)
        return bytes(buf)

    def _recv_packet(self) -> tuple[int, int, bytes]:
        head = self._recv_exact(_HEADER.size)
        magic, dev_id, packet_id, data_len = _HEADER.unpack(head)
        if magic != _MAGIC:
            raise OpenRGBError(f"bad magic: {magic!r}")
        data = self._recv_exact(data_len) if data_len else b""
        return dev_id, packet_id, data

    # ── handshake / enumerate ──────────────────────────────────────────

    def _handshake(self) -> None:
        # SET_CLIENT_NAME — null-terminated UTF-8. Pre-protocol-2
        # servers ignore this; protocol 2+ requires it before
        # REQUEST_PROTOCOL_VERSION.
        with self._lock:
            self._send(0, SET_CLIENT_NAME,
                       self.client_name.encode("utf-8") + b"\x00")
            self._send(0, REQUEST_PROTOCOL_VERSION,
                       struct.pack("<I", PROTOCOL_VERSION_CLIENT))
            _, _, resp = self._recv_packet()
        # v1.5.0-beta-hotfix3: the server replies with ITS max
        # supported protocol, NOT the negotiated value. The client
        # must take min(client_claim, server_reply) and use that
        # version for all subsequent requests. Caught against
        # OpenRGB 1.0rc2 (server claimed proto 5 → previous code
        # blindly used 5 → tried to walk proto-5 controller data
        # with our proto-4 parser → "subsection not found").
        server_proto = 0
        if len(resp) >= 4:
            server_proto = struct.unpack("<I", resp[:4])[0]
        self.protocol_version = min(PROTOCOL_VERSION_CLIENT,
                                     server_proto if server_proto > 0
                                     else PROTOCOL_VERSION_CLIENT)
        print(f"[openrgb] handshake: server proto={server_proto}, "
              f"negotiated={self.protocol_version}")

    def _enumerate(self) -> None:
        with self._lock:
            self._send(0, REQUEST_CONTROLLER_COUNT)
            _, _, resp = self._recv_packet()
        count = struct.unpack("<I", resp[:4])[0] if len(resp) >= 4 else 0
        # v1.5.0-beta-hotfix2: capture per-device parse failures with a
        # short hex prefix so a maintainer can diagnose a stuck enumerate
        # ("verbunden · 0 Geräte") without having to attach a debugger
        # to a windowless PyInstaller build. Surfaced via /openrgb/status
        # → `parseErrors`.
        self.last_parse_errors: list[str] = []
        self.last_protocol_used: int = self.protocol_version
        print(f"[openrgb] enumerate: count={count} "
              f"proto={self.protocol_version}")
        devices: list[dict] = []
        for i in range(count):
            data = b""
            try:
                with self._lock:
                    self._send(i, REQUEST_CONTROLLER_DATA,
                               struct.pack("<I", self.protocol_version))
                    _, _, data = self._recv_packet()
                info = _parse_controller_data(data, self.protocol_version)
                devices.append({
                    "id":        i,
                    "name":      info["name"],
                    "type":      info["type"],
                    "led_count": info["led_count"],
                })
                print(f"[openrgb] device {i}: {info['name']!r} "
                      f"({info['led_count']} LEDs, {len(data)} B)")
            except (OpenRGBError, struct.error, UnicodeDecodeError, ValueError) as e:
                # Keep a short hex prefix (max 64 B) so the wire format
                # can be reconstructed for diagnosis without dumping the
                # whole 1-3 KB payload into the log.
                head = data[:64].hex() if data else "(no data)"
                msg = (f"device {i} parse failed at proto "
                       f"{self.protocol_version}: {e} — first 64B={head}")
                self.last_parse_errors.append(msg)
                print(f"[openrgb] {msg}")
        self.devices = devices
        print(f"[openrgb] enumerate done: "
              f"{len(devices)}/{count} device(s) parsed")

    # ── output ─────────────────────────────────────────────────────────

    def push_color(self, device_id: int, rgb: tuple[int, int, int]) -> bool:
        """Paint every LED of `device_id` with the same RGB triple.
        Returns False if the device isn't known or the write fails;
        does NOT raise so the caller can keep going."""
        dev = next((d for d in self.devices if d["id"] == device_id), None)
        if dev is None or dev["led_count"] <= 0:
            return False
        n = int(dev["led_count"])
        r, g, b = (int(c) & 0xff for c in rgb)
        # UPDATE_LEDS payload:
        #   uint32 data_size  (whole payload including itself)
        #   uint16 num_colors
        #   uint32[num_colors]  packed as B G R 0 little-endian
        # OpenRGB stores colours as 0x00BBGGRR in a uint32, but on the
        # wire that LE-uint32 happens to be the byte sequence R G B 0.
        body = struct.pack("<H", n) + bytes((r, g, b, 0)) * n
        payload = struct.pack("<I", len(body) + 4) + body
        try:
            with self._lock:
                self._send(device_id, RGBCONTROLLER_UPDATELEDS, payload)
            return True
        except (OSError, OpenRGBError) as e:
            print(f"[openrgb] push to device {device_id} failed: {e}")
            return False

    # ── input (OpenRGB-as-source path) ────────────────────────────────

    def get_colors(self, device_id: int) -> list[tuple[int, int, int]]:
        """v1.5: pull the current per-LED colour array for `device_id`.
        Used by `OpenRgbInputManager` to mirror whichever effect engine
        (SignalRGB plugin, OpenRGB-native effect, …) is driving that
        device. Empty list on any failure — caller polls again next
        tick.

        Implementation note: OpenRGB doesn't expose a dedicated
        \"read current colours\" packet. The colours travel as the
        tail of REQUEST_CONTROLLER_DATA, so we re-request the whole
        descriptor and parse forward. That's ~1-3 KB per poll — fine
        at the 30 Hz cap we run."""
        try:
            with self._lock:
                self._send(device_id, REQUEST_CONTROLLER_DATA,
                           struct.pack("<I", self.protocol_version))
                _, _, data = self._recv_packet()
            info = _parse_controller_data(
                data, self.protocol_version, with_colors=True)
            return info.get("colors", []) or []
        except (OSError, OpenRGBError, struct.error,
                UnicodeDecodeError, ValueError) as e:
            print(f"[openrgb] get_colors({device_id}) failed: {e}")
            return []

    def push_strip(self, device_id: int, colors) -> bool:
        """Paint per-LED from `colors` (iterable of (r,g,b) triples).
        Extra LEDs beyond `len(colors)` are filled with the last
        colour; extra `colors` beyond LED count are discarded."""
        dev = next((d for d in self.devices if d["id"] == device_id), None)
        if dev is None or dev["led_count"] <= 0:
            return False
        n = int(dev["led_count"])
        seq = list(colors)[:n]
        if not seq:
            return False
        while len(seq) < n:
            seq.append(seq[-1])
        body = struct.pack("<H", n)
        body += b"".join(bytes((int(r) & 0xff, int(g) & 0xff, int(b) & 0xff, 0))
                         for (r, g, b) in seq)
        payload = struct.pack("<I", len(body) + 4) + body
        try:
            with self._lock:
                self._send(device_id, RGBCONTROLLER_UPDATELEDS, payload)
            return True
        except (OSError, OpenRGBError) as e:
            print(f"[openrgb] strip push to device {device_id} failed: {e}")
            return False


# ─── controller-data parser ───────────────────────────────────────────


def _read_string(data: bytes, pos: int) -> tuple[str, int]:
    """Read a length-prefixed UTF-8 string.

    OpenRGB's controller-data string format is `uint16-LE length` +
    `length` bytes of UTF-8 (length INCLUDES the trailing null byte
    that the C++ side writes). We strip the trailing null when
    decoding but advance `pos` by the full declared length so
    subsequent fields stay aligned even if the string body is
    malformed.

    v1.5.0-beta-hotfix3: previous implementation searched for
    `\\x00` as the terminator. That's the SET_CLIENT_NAME wire
    format (null-terminated), but controller_data uses length
    prefixes — so we'd land in mid-string territory, consume the
    length bytes as part of the string, then over-shoot every
    subsequent string. Symptom: parser exception "subsection not
    found" on every device, enumerate returned 0 devices."""
    if pos + 2 > len(data):
        raise ValueError(f"string length prefix past end at {pos}")
    n = struct.unpack_from("<H", data, pos)[0]
    pos += 2
    if pos + n > len(data):
        raise ValueError(f"string body past end at {pos} (want {n})")
    s = data[pos:pos + n].rstrip(b"\x00").decode("utf-8", "replace")
    return s, pos + n


def _parse_controller_data(data: bytes, version: int,
                            with_colors: bool = False) -> dict:
    """Parse REQUEST_CONTROLLER_DATA. Always returns name + LED count;
    with `with_colors=True` also returns the current per-LED colour
    array. Skips past mode + zone sections by walking their declared
    structure — OpenRGB's protocol changed a couple of times across
    the 0.6 → 0.9 line, so we branch on `version`.

    Returns {name, type, led_count, [colors: list[(r,g,b)]]}. Raises
    ValueError on malformed data."""
    pos = 0
    # uint32 data_size + uint32 device_type
    if len(data) < 8:
        raise ValueError("controller data too short")
    _data_size, device_type = struct.unpack_from("<II", data, pos)
    pos += 8

    name, pos        = _read_string(data, pos)
    # v1.5.0-beta-hotfix4: protocol 1+ added a `vendor` string
    # between name and description. Without consuming it the
    # whole subsequent walk slid one field forward — symptom:
    # huge bogus string lengths (~14k-20k) on the 4th/5th read
    # because we'd be parsing mid-mode-block as a length prefix.
    if version >= 1:
        _vendor, pos = _read_string(data, pos)
    description, pos = _read_string(data, pos)
    _version, pos    = _read_string(data, pos)
    _serial, pos     = _read_string(data, pos)
    _location, pos   = _read_string(data, pos)

    # num_modes uint16, active_mode int32
    num_modes = struct.unpack_from("<H", data, pos)[0]; pos += 2
    pos += 4   # active_mode

    # Each mode: name + a chain of uint32s + a colour array.
    # Mode struct size after the name string:
    #   Protocol 0-2:   9 × uint32 = 36 bytes + uint16 num_colors + 4*num_colors
    #     fields: value, flags, speed_min, speed_max, colors_min,
    #             colors_max, speed, direction, color_mode
    #   Protocol 3+:  12 × uint32 = 48 bytes + uint16 num_colors + 4*num_colors
    #     fields: value, flags, speed_min, speed_max, brightness_min,
    #             brightness_max, colors_min, colors_max, speed,
    #             brightness, direction, color_mode
    # v1.5.0-beta hotfix: was 44 (11 × uint32) — off-by-one missed the
    # `brightness` field added in proto 3, so every device's mode block
    # fell out of alignment, num_zones overflowed past end-of-buffer,
    # _parse_controller_data raised ValueError, and enumerate() returned
    # an empty device list. Symptom in the Configurator: "verbunden · 0
    # Geräte" against a connected OpenRGB SDK with real devices.
    mode_uint_block = 48 if version >= 3 else 36
    for _ in range(num_modes):
        _mode_name, pos = _read_string(data, pos)
        pos += mode_uint_block
        if pos + 2 > len(data):
            raise ValueError("truncated mode block")
        n_colors = struct.unpack_from("<H", data, pos)[0]; pos += 2
        pos += 4 * n_colors

    # num_zones uint16
    if pos + 2 > len(data):
        raise ValueError("truncated before zones")
    num_zones = struct.unpack_from("<H", data, pos)[0]; pos += 2

    for _ in range(num_zones):
        _zone_name, pos = _read_string(data, pos)
        # zone fields: type uint32, leds_min uint32, leds_max uint32,
        # leds_count uint32, matrix_size uint16
        pos += 4 * 4   # type + leds_min + leds_max + leds_count
        if pos + 2 > len(data):
            raise ValueError("truncated zone header")
        matrix_size = struct.unpack_from("<H", data, pos)[0]; pos += 2
        if matrix_size > 0:
            # matrix_height uint32, matrix_width uint32, then height*width uint32s
            if pos + 8 > len(data):
                raise ValueError("truncated matrix header")
            mh, mw = struct.unpack_from("<II", data, pos); pos += 8
            pos += 4 * mh * mw
        # Protocol 4+ adds segments per zone after the matrix:
        #   uint16 num_segments
        #   per segment: string name + uint32 type + uint32 start + uint32 leds_count
        if version >= 4:
            if pos + 2 > len(data):
                raise ValueError("truncated segments header")
            num_segs = struct.unpack_from("<H", data, pos)[0]; pos += 2
            for _ in range(num_segs):
                _seg_name, pos = _read_string(data, pos)
                pos += 4 * 3

    # num_leds uint16, then per LED: string name + uint32 value
    if pos + 2 > len(data):
        raise ValueError("truncated before LED count")
    num_leds = struct.unpack_from("<H", data, pos)[0]; pos += 2
    result = {"name": name, "type": int(device_type),
              "led_count": int(num_leds)}
    if not with_colors:
        return result
    # v1.5: walk past the per-LED descriptors (string + uint32) so we
    # land on the colour array at the end. Used by OpenRGB-as-source
    # input — see OpenRGBClient.get_colors.
    try:
        for _ in range(num_leds):
            _led_name, pos = _read_string(data, pos)
            pos += 4   # uint32 LED value (raw register, we don't need it)
        if pos + 2 > len(data):
            raise ValueError("truncated before colors")
        n_colors = struct.unpack_from("<H", data, pos)[0]; pos += 2
        colors: list[tuple[int, int, int]] = []
        for _ in range(n_colors):
            if pos + 4 > len(data):
                break
            r, g, b, _ = data[pos], data[pos + 1], data[pos + 2], data[pos + 3]
            colors.append((r, g, b))
            pos += 4
        result["colors"] = colors
    except (struct.error, ValueError):
        result["colors"] = []
    return result
