"""
Minimal MQTT 3.1.1 client for the bridge's Home Assistant / MQTT
integration (v1.5.0-beta).

Why custom instead of paho-mqtt?
  • Keeps the bridge's MIT distribution clean (paho-mqtt is dual-
    licensed EPL-2.0 / EDL-1.0 which works for MIT bundling but
    requires extra attribution + per-file notice preservation).
  • Our needs are tiny: connect, publish (QoS 0), subscribe (QoS 0),
    keepalive. A ~400 LOC self-contained module is preferable to
    pulling in a generic client with reconnect-backoff, SSL,
    persistence, MQTT 5.0 properties, etc.
  • Same architectural pattern as openrgb_client.py + sacn_codec.py
    (one focused module per protocol, stdlib only).

Implements the bare minimum of the MQTT 3.1.1 spec (CONNECT / CONNACK
/ PUBLISH / SUBSCRIBE / SUBACK / PINGREQ / PINGRESP / DISCONNECT)
needed for typical Home Assistant integration. No QoS 1/2 (no PUBACK
/ PUBREC / PUBREL / PUBCOMP handling), no MQTT 5.0 properties, no
TLS. All retained / non-retained publish supported. LWT (last will)
supported via CONNECT flags.

Spec reference: MQTT Version 3.1.1 (OASIS standard).
"""

from __future__ import annotations

import socket
import struct
import threading
import time


# ─── packet types ─────────────────────────────────────────────────────────

CONNECT     = 0x10
CONNACK     = 0x20
PUBLISH     = 0x30
SUBSCRIBE   = 0x82   # type 8 + reserved flags (0010)
SUBACK      = 0x90
UNSUBSCRIBE = 0xa2
UNSUBACK    = 0xb0
PINGREQ     = 0xc0
PINGRESP    = 0xd0
DISCONNECT  = 0xe0


# ─── variable-length integer helpers ─────────────────────────────────────

def _encode_remaining_length(n: int) -> bytes:
    """MQTT's "remaining length" is a 1-4 byte variable-length int
    (sec. 2.2.3 of the spec). Continuation bit in MSB."""
    out = bytearray()
    while True:
        byte = n & 0x7f
        n >>= 7
        if n > 0:
            byte |= 0x80
        out.append(byte)
        if n == 0:
            break
    return bytes(out)


def _decode_remaining_length(sock) -> int:
    """Read the variable-length remaining-length field from `sock`.
    Raises if the field is malformed (>4 bytes / 268435455 max)."""
    multiplier = 1
    value = 0
    for _ in range(4):
        b = sock.recv(1)
        if not b:
            raise ConnectionError("socket closed during length field")
        digit = b[0]
        value += (digit & 0x7f) * multiplier
        if digit & 0x80 == 0:
            return value
        multiplier *= 128
    raise ValueError("malformed remaining length")


def _encode_utf8(s: str) -> bytes:
    body = s.encode("utf-8")
    return struct.pack(">H", len(body)) + body


# ─── client ──────────────────────────────────────────────────────────────

class MQTTError(Exception):
    pass


class MQTTClient:
    """Single-broker MQTT 3.1.1 client. One TCP connection + one
    background read thread + one app-driven publish path. Thread-safe
    via a single `_send_lock`; the read thread doesn't need to send.

    Public API:
        connect()                  -> bool
        disconnect()
        publish(topic, payload, retain=False, qos=0)
        subscribe(topic_filter, on_message_callback)
        is_connected               -> bool

    `on_message` callback receives (topic: str, payload: bytes).
    """

    KEEPALIVE_S = 30
    READ_TIMEOUT_S = 5.0

    def __init__(self,
                 host: str = "localhost",
                 port: int = 1883,
                 client_id: str = "signalrgb-wallpaper",
                 username: str = "",
                 password: str = "",
                 keepalive: int = KEEPALIVE_S,
                 will_topic: str = "",
                 will_payload: bytes = b"offline",
                 will_retain: bool = True,
                 timeout: float = 5.0):
        self.host = host
        self.port = port
        self.client_id = (client_id or "signalrgb-wallpaper")[:23]
        self.username = username
        self.password = password
        self.keepalive = max(10, int(keepalive))
        self.will_topic = will_topic
        self.will_payload = will_payload
        self.will_retain = will_retain
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._subs: dict[str, list] = {}    # filter -> [callback…]
        self._reader_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_send_ts = 0.0
        self._connected = False
        self.last_error: str = ""

    @property
    def is_connected(self) -> bool:
        return self._connected and self._sock is not None

    # ── lifecycle ─────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Open the TCP socket + send CONNECT + wait for CONNACK.
        Returns True on success, False on any failure. Safe to call
        repeatedly — closes the prior socket first."""
        self.disconnect()
        self._stop.clear()
        try:
            s = socket.create_connection(
                (self.host, self.port), timeout=self.timeout)
            s.settimeout(self.READ_TIMEOUT_S)
            self._sock = s
            self._send_connect()
            ack = self._recv_packet()
            if ack is None or ack[0] != CONNACK:
                raise MQTTError(f"expected CONNACK, got {ack[0] if ack else None}")
            # CONNACK variable header: session_present + return_code
            if len(ack[1]) < 2:
                raise MQTTError("truncated CONNACK")
            return_code = ack[1][1]
            if return_code != 0:
                raise MQTTError(f"CONNACK return code {return_code}")
            self._connected = True
            self.last_error = ""
            self._reader_thread = threading.Thread(
                target=self._read_loop, daemon=True,
                name=f"mqtt-read-{self.client_id}")
            self._reader_thread.start()
            return True
        except (OSError, MQTTError, struct.error) as e:
            self.last_error = str(e)
            self.disconnect()
            return False

    def disconnect(self) -> None:
        self._stop.set()
        self._connected = False
        if self._sock is not None:
            try:
                # Best-effort DISCONNECT — the broker treats a
                # closed socket as ungraceful disconnect (LWT fires);
                # sending DISCONNECT explicitly suppresses LWT.
                with self._send_lock:
                    self._sock.sendall(bytes([DISCONNECT, 0]))
            except Exception:
                pass
            try: self._sock.close()
            except Exception: pass
            self._sock = None

    # ── transport ─────────────────────────────────────────────────────

    def _send_connect(self) -> None:
        # Variable header
        var = _encode_utf8("MQTT")              # protocol name
        var += b"\x04"                          # protocol level (3.1.1)
        flags = 0x02                            # clean session
        if self.will_topic:
            flags |= 0x04                       # will flag
            if self.will_retain:
                flags |= 0x20
        if self.username:
            flags |= 0x80
        if self.password:
            flags |= 0x40
        var += bytes([flags])
        var += struct.pack(">H", self.keepalive)
        # Payload: client id (+ will + creds in spec order)
        payload = _encode_utf8(self.client_id)
        if self.will_topic:
            payload += _encode_utf8(self.will_topic)
            payload += struct.pack(">H", len(self.will_payload)) + self.will_payload
        if self.username:
            payload += _encode_utf8(self.username)
        if self.password:
            payload += _encode_utf8(self.password)
        body = var + payload
        head = bytes([CONNECT]) + _encode_remaining_length(len(body))
        with self._send_lock:
            self._sock.sendall(head + body)
            self._last_send_ts = time.monotonic()

    def _send_pingreq(self) -> None:
        if self._sock is None:
            return
        with self._send_lock:
            try:
                self._sock.sendall(bytes([PINGREQ, 0]))
                self._last_send_ts = time.monotonic()
            except OSError as e:
                self.last_error = f"pingreq: {e}"
                self._connected = False

    def publish(self, topic: str, payload,
                retain: bool = False, qos: int = 0) -> bool:
        """Publish `payload` (str or bytes) to `topic`. QoS 0 only —
        higher QoS levels need ACK tracking which our HA use case
        doesn't justify. Returns False on send failure."""
        if not self.is_connected:
            return False
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        flags = PUBLISH | ((qos & 0x03) << 1) | (0x01 if retain else 0)
        var = _encode_utf8(topic)
        # QoS 0 has no packet identifier
        body = var + payload
        head = bytes([flags]) + _encode_remaining_length(len(body))
        try:
            with self._send_lock:
                self._sock.sendall(head + body)
                self._last_send_ts = time.monotonic()
            return True
        except OSError as e:
            self.last_error = f"publish: {e}"
            self._connected = False
            return False

    def subscribe(self, topic_filter: str, on_message) -> bool:
        """Subscribe to `topic_filter` (supports `+` and `#`
        wildcards) and register `on_message(topic, payload_bytes)`
        for matches. Multiple subscribes to the same filter chain
        the callbacks."""
        self._subs.setdefault(topic_filter, []).append(on_message)
        if not self.is_connected:
            return False
        # Variable header: packet identifier (uint16). We don't
        # track SUBACK so any non-zero ID works.
        var = struct.pack(">H", 1)
        # Payload: topic filter + requested QoS (0)
        payload = _encode_utf8(topic_filter) + b"\x00"
        body = var + payload
        head = bytes([SUBSCRIBE]) + _encode_remaining_length(len(body))
        try:
            with self._send_lock:
                self._sock.sendall(head + body)
                self._last_send_ts = time.monotonic()
            return True
        except OSError as e:
            self.last_error = f"subscribe: {e}"
            self._connected = False
            return False

    # ── read path ─────────────────────────────────────────────────────

    def _recv_exact(self, n: int) -> bytes:
        if self._sock is None:
            raise ConnectionError("socket closed")
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("socket closed mid-packet")
            buf.extend(chunk)
        return bytes(buf)

    def _recv_packet(self):
        """Returns (fixed_header_byte, body_bytes) or None on
        recv-timeout. Raises ConnectionError on a clean close so the
        outer read loop tears down + exits instead of spinning on
        zero-byte recvs at 100 % CPU (v1.5.0-beta-hotfix: that
        spin showed up as Configurator-tab-pegging the user's PC at
        95 °C every time the broker dropped the TCP)."""
        if self._sock is None:
            return None
        try:
            first = self._sock.recv(1)
        except (TimeoutError, socket.timeout):
            return None
        if not first:
            raise ConnectionError("broker closed the socket")
        length = _decode_remaining_length(self._sock)
        body = self._recv_exact(length) if length else b""
        return (first[0], body)

    def _read_loop(self) -> None:
        """Background read thread. Handles incoming PUBLISH +
        SUBACK + PINGRESP. Dispatches PUBLISH bodies to registered
        callbacks. Sends PINGREQ when keepalive elapses without
        outbound traffic."""
        while not self._stop.is_set() and self._sock is not None:
            # Heartbeat
            if time.monotonic() - self._last_send_ts > self.keepalive * 0.75:
                self._send_pingreq()
            try:
                pkt = self._recv_packet()
            except (OSError, ConnectionError, ValueError) as e:
                self.last_error = f"read: {e}"
                self._connected = False
                return
            if pkt is None:
                continue
            ptype = pkt[0] & 0xf0
            body = pkt[1]
            if ptype == PUBLISH:
                self._handle_publish(pkt[0], body)
            elif ptype in (SUBACK, UNSUBACK, PINGRESP):
                # Acknowledgements — we don't track ids so just
                # eat them quietly.
                pass
            elif ptype == PINGRESP:
                pass

    def _handle_publish(self, header_byte: int, body: bytes) -> None:
        # Topic name (uint16 length + bytes)
        if len(body) < 2:
            return
        tlen = struct.unpack(">H", body[:2])[0]
        if len(body) < 2 + tlen:
            return
        topic = body[2:2 + tlen].decode("utf-8", "replace")
        pos = 2 + tlen
        # QoS > 0 carries a packet identifier (uint16) — skip
        qos = (header_byte >> 1) & 0x03
        if qos > 0 and len(body) >= pos + 2:
            pos += 2
        payload = body[pos:]
        # Dispatch — match any subscription whose filter matches
        for filt, cbs in list(self._subs.items()):
            if _topic_matches(filt, topic):
                for cb in cbs:
                    try:
                        cb(topic, payload)
                    except Exception as e:
                        print(f"[mqtt] callback for {filt!r} raised: {e}")


# ─── topic matching ──────────────────────────────────────────────────────

def _topic_matches(filt: str, topic: str) -> bool:
    """MQTT topic-filter matching with `+` (single-level) and `#`
    (multi-level) wildcards."""
    f = filt.split("/")
    t = topic.split("/")
    i = 0
    while i < len(f):
        if f[i] == "#":
            return True
        if i >= len(t):
            return False
        if f[i] == "+" or f[i] == t[i]:
            i += 1
            continue
        return False
    return i == len(t)
