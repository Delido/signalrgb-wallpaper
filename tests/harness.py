"""Shared helpers for the bridge test-suite.

These tests import bridge.py directly and exercise its classes in-process
against fake writers. Nothing here needs a running SignalRGBBridge.exe,
a live SignalRGB instance, or a network port — which is what makes them
runnable in CI (and repeatable, unlike smoke_test.py, whose assertions
are polluted by whatever the real plugin happens to be broadcasting).

Two things about bridge.py make importing it awkward, both handled here:

  * It replaces sys.stdout with its own _LogStream on import (for the
    PyInstaller --noconsole build), so any print() from a test would
    vanish. `emit()` writes to the real stderr instead.
  * It expects its sibling modules (openrgb_client, mqtt_client, …) on
    sys.path. `load_bridge()` adds wallpaper_bridge/ before importing so
    those optional imports resolve instead of printing load failures.
"""

import asyncio
import importlib.util
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_DIR = REPO_ROOT / "wallpaper_bridge"
BRIDGE_PY = BRIDGE_DIR / "bridge.py"

# Captured before bridge.py can swap sys.stdout out from under us.
_REAL_STDERR = sys.stderr


def emit(*args):
    """print() that survives bridge.py's stdout takeover."""
    print(*args, file=_REAL_STDERR)


_cached = None


def load_bridge():
    """Import bridge.py as a module, once per process."""
    global _cached
    if _cached is not None:
        return _cached
    if str(BRIDGE_DIR) not in sys.path:
        sys.path.insert(0, str(BRIDGE_DIR))
    spec = importlib.util.spec_from_file_location("bridge_under_test", BRIDGE_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bridge_under_test"] = mod
    spec.loader.exec_module(mod)
    _cached = mod
    return mod


# ── assertions ───────────────────────────────────────────────────────────

class Results:
    """Minimal test recorder. Avoids a pytest dependency so the suite
    runs with a bare `python tests/run_all.py` on any machine that can
    already build the project."""

    def __init__(self, name):
        self.name = name
        self.passed = 0
        self.failed = []

    def check(self, label, cond, detail=""):
        if cond:
            self.passed += 1
            emit(f"  PASS  {label}")
        else:
            self.failed.append(label)
            emit(f"  FAIL  {label}" + (f"  — {detail}" if detail else ""))
        return bool(cond)

    def eq(self, label, actual, expected):
        return self.check(label, actual == expected,
                          f"expected {expected!r}, got {actual!r}")

    @property
    def ok(self):
        return not self.failed

    def summary(self):
        total = self.passed + len(self.failed)
        emit(f"  {self.passed}/{total} passed")
        return self.ok


# ── WS frame helpers ─────────────────────────────────────────────────────

def mask_client_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Build a client→server frame. Browser frames MUST be masked per
    RFC 6455 and bridge.py rejects unmasked ones, so tests that feed
    read_client_text_frame() need this rather than _encode_frame()."""
    header = bytearray([0x80 | (opcode & 0x0F)])
    n = len(payload)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", n)
    mask = b"\x01\x02\x03\x04"
    header += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return bytes(header) + masked


def parse_server_frames(buf: bytes):
    """Walk a server→client byte stream, yielding (opcode, payload).
    Server frames are never masked."""
    out = []
    i = 0
    while i + 1 < len(buf):
        opcode = buf[i] & 0x0F
        n = buf[i + 1] & 0x7F
        i += 2
        if n == 126:
            n = struct.unpack(">H", buf[i:i + 2])[0]
            i += 2
        elif n == 127:
            n = struct.unpack(">Q", buf[i:i + 8])[0]
            i += 8
        out.append((opcode, bytes(buf[i:i + n])))
        i += n
    return out


def opcodes_in(buf: bytes):
    return [op for op, _ in parse_server_frames(buf)]


# ── fake transport / writer ──────────────────────────────────────────────

class FakeTransport:
    def __init__(self):
        self.closing = False
        self.buffer_size = 0

    def get_write_buffer_size(self):
        return self.buffer_size

    def is_closing(self):
        return self.closing

    def close(self):
        self.closing = True


class FakeWriter:
    """Stands in for an asyncio StreamWriter.

    `fail_on_drain` models the half-open socket from issue #2: write()
    succeeds (the bytes land in the transport buffer) but drain() raises
    once the kernel actually tries to push them. That asymmetry is
    exactly why broadcast_frame's un-drained write() couldn't detect a
    dead peer and the keepalive's drain() can.
    """

    def __init__(self, fail_on_drain=False, fail_on_write=False):
        self.written = bytearray()
        self.transport = FakeTransport()
        self.closed = False
        self.fail_on_drain = fail_on_drain
        self.fail_on_write = fail_on_write

    def write(self, data):
        if self.fail_on_write or self.transport.closing:
            raise ConnectionResetError("socket closed")
        self.written += data

    async def drain(self):
        if self.fail_on_drain:
            raise ConnectionResetError("half-open socket")

    def close(self):
        self.closed = True
        self.transport.closing = True

    def is_closing(self):
        return self.transport.closing


def make_broadcaster(bridge, loop, **overrides):
    """Construct a Broadcaster with inert callbacks."""
    kwargs = dict(
        get_settings=lambda s: {"frameRate": 30},
        get_screen_count=lambda: 2,
        update_background=lambda *a, **k: None,
        get_paused=lambda: False,
        on_widget_command=lambda *a, **k: None,
        get_bridge_state=lambda: {},
    )
    kwargs.update(overrides)
    return bridge.Broadcaster(loop, **kwargs)


def run(coro):
    return asyncio.run(coro)
