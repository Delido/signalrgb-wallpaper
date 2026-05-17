"""
Smoke-test the multi-screen bridge: send a fake UDP frame for screen=1
and verify that a WS client subscribed to ?screen=1 receives it while a
client on ?screen=0 does NOT.  Run while SignalRGBBridge.exe is up.
"""

import asyncio
import base64
import hashlib
import os
import socket
import struct
import sys
import time


WS_HOST = "127.0.0.1"
WS_PORT = 17320
WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_handshake(target: str) -> tuple[socket.socket, bytes]:
    s = socket.socket()
    s.connect((WS_HOST, WS_PORT))
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {WS_HOST}:{WS_PORT}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode()
    s.sendall(req)
    expect = base64.b64encode(hashlib.sha1(key.encode() + WS_GUID).digest()).decode()
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = s.recv(1024)
        if not chunk:
            raise RuntimeError("server closed during handshake")
        resp += chunk
    if expect.encode() not in resp:
        raise RuntimeError(f"bad handshake; expected accept token {expect!r}, got: {resp!r}")
    return s, resp


def read_one_binary_frame(s: socket.socket, timeout: float) -> bytes | None:
    """Skip text/control frames and return the next binary frame's body.

    The bridge sends an initial JSON text frame with settings on every
    upgrade, so a naive "read one frame" reader gets misaligned. We
    consume every frame off the wire and only return when we see a
    binary one (opcode 0x2).
    """
    s.settimeout(timeout)
    try:
        while True:
            header = s.recv(2)
            if len(header) < 2:
                return None
            opcode = header[0] & 0x0f
            n = header[1] & 0x7f
            if n == 126:
                ext = s.recv(2)
                n = struct.unpack(">H", ext)[0]
            elif n == 127:
                ext = s.recv(8)
                n = struct.unpack(">Q", ext)[0]
            body = b""
            while len(body) < n:
                chunk = s.recv(n - len(body))
                if not chunk:
                    return None
                body += chunk
            if opcode == 0x2:
                return body
            # else: text/ping/etc — drop and keep reading
    except (socket.timeout, ConnectionResetError):
        return None


def send_udp(screen: int, w: int = 2, h: int = 2) -> bytes:
    pkt = bytearray([0x53, 0x52, screen, (w >> 8) & 0xff, w & 0xff, (h >> 8) & 0xff, h & 0xff])
    for i in range(w * h):
        pkt += bytes([i * 30 & 0xff, 0x40, 0xff])
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.sendto(bytes(pkt), (WS_HOST, WS_PORT))
    return bytes(pkt)


def main():
    print("=== bridge multi-screen smoke test ===")
    ws0, _ = ws_handshake("/?screen=0")
    ws1, _ = ws_handshake("/?screen=1")
    print("WS subscribers connected: screen=0, screen=1")

    # Tiny delay so the bridge finishes registering both clients
    time.sleep(0.2)

    expected = send_udp(screen=1)
    print(f"sent UDP for screen=1 ({len(expected)} bytes)")

    frame0 = read_one_binary_frame(ws0, timeout=0.5)
    frame1 = read_one_binary_frame(ws1, timeout=0.5)

    ok = True
    if frame1 == expected:
        print(f"  [PASS] screen=1 client received the frame ({len(frame1)} bytes)")
    else:
        print(f"  [FAIL] screen=1 client got: {frame1!r}")
        ok = False
    if frame0 is None:
        print("  [PASS] screen=0 client got nothing (correctly filtered)")
    else:
        print(f"  [FAIL] screen=0 client unexpectedly got: {frame0!r}")
        ok = False

    expected2 = send_udp(screen=0)
    print(f"sent UDP for screen=0 ({len(expected2)} bytes)")
    frame0b = read_one_binary_frame(ws0, timeout=0.5)
    frame1b = read_one_binary_frame(ws1, timeout=0.5)
    if frame0b == expected2:
        print(f"  [PASS] screen=0 client received the frame ({len(frame0b)} bytes)")
    else:
        print(f"  [FAIL] screen=0 client got: {frame0b!r}")
        ok = False
    if frame1b is None:
        print("  [PASS] screen=1 client got nothing (correctly filtered)")
    else:
        print(f"  [FAIL] screen=1 client unexpectedly got: {frame1b!r}")
        ok = False

    ws0.close()
    ws1.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
