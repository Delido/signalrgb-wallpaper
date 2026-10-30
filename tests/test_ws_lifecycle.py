"""WebSocket client lifecycle: registration, keepalive, reaping, cleanup.

Regression cover for issue #2 and the bugs found alongside it. Everything
here runs in-process against fake writers — no bridge process, no ports,
no live SignalRGB instance.

Why this file exists: the sleep/resume bug took two releases to fix, and
the wrong fix shipped first. Both the wrong theory and the right one
would have been settled in seconds by tests at this level.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    Results, emit, load_bridge, make_broadcaster,
    FakeWriter, mask_client_frame, opcodes_in, parse_server_frames,
)

bridge = load_bridge()
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


async def test_frame_decoding(r):
    """read_client_text_frame must classify each opcode correctly.

    Pre-2.4.1 the bridge dropped pings on the floor and never replied,
    which is a protocol violation and blinds us to client liveness.
    """
    async def decode(frame_bytes):
        reader = asyncio.StreamReader()
        reader.feed_data(frame_bytes)
        reader.feed_eof()
        return await bridge.read_client_text_frame(reader)

    r.eq("text frame decodes to its payload",
         await decode(mask_client_frame(0x1, b'{"type":"hello"}')),
         '{"type":"hello"}')
    r.eq("pong decodes to PONG_SENTINEL",
         await decode(mask_client_frame(OPCODE_PONG)), bridge.PONG_SENTINEL)
    r.eq("client ping decodes to PONG_SENTINEL",
         await decode(mask_client_frame(OPCODE_PING)), bridge.PONG_SENTINEL)
    r.eq("close frame decodes to None",
         await decode(mask_client_frame(0x8)), None)
    r.eq("binary frame is ignored (empty string)",
         await decode(mask_client_frame(0x2, b"\x00\x01")), "")

    # Oversized frames must be refused rather than buffered — a header
    # claiming a huge payload would otherwise OOM the bridge.
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x81\xFF" + (10 * 1024 * 1024).to_bytes(8, "big") + b"\x00" * 4)
    reader.feed_eof()
    r.eq("oversized frame is rejected",
         await bridge.read_client_text_frame(reader), None)


async def test_add_and_remove(r):
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    w = FakeWriter()

    await b.add(w, 0, "wallpaper")
    r.check("client lands in clients_by_screen", w in b.clients_by_screen.get(0, set()))
    r.eq("role is recorded", b.client_roles.get(w), "wallpaper")
    r.check("liveness stamp is seeded", w in b._client_last_seen)
    r.check("initial settings push happened", len(w.written) > 0)

    await b.remove(w)
    r.check("client removed from screen set", w not in b.clients_by_screen.get(0, set()))
    r.check("role cleaned up", w not in b.client_roles)
    r.check("liveness stamp cleaned up", w not in b._client_last_seen)
    r.check("transport closed", w.closed)


async def test_remove_sweeps_all_screens(r):
    """Regression: remove() used to `return` from inside its loop over
    clients_by_screen, so a writer registered on more than one screen
    was only dropped from the first. The leftover entry kept receiving
    broadcasts for a socket that was already closed."""
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    w = FakeWriter()

    await b.add(w, 0, "wallpaper")
    async with b._lock:
        b.clients_by_screen.setdefault(1, set()).add(w)
        b.clients_by_screen.setdefault(2, set()).add(w)

    await b.remove(w)
    leftovers = [s for s, cs in b.clients_by_screen.items() if w in cs]
    r.check("writer removed from every screen", not leftovers,
            f"still present on screens {leftovers}")


async def test_remove_is_idempotent(r):
    """remove() is now reachable from both the read loop and the
    keepalive reaper, so the two can race on the same client."""
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    w = FakeWriter()
    await b.add(w, 0, "wallpaper")
    await b.remove(w)
    try:
        await b.remove(w)
        await b.remove(FakeWriter())  # never added at all
        r.check("repeated remove() is a safe no-op", True)
    except Exception as e:
        r.check("repeated remove() is a safe no-op", False, repr(e))


async def test_keepalive_pings(r):
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    b.KEEPALIVE_INTERVAL_S = 0.05
    b.CLIENT_IDLE_TIMEOUT_S = 10.0
    w = FakeWriter()
    await b.add(w, 0, "wallpaper")
    w.written.clear()  # drop the initial settings push

    task = loop.create_task(b._keepalive_loop())
    await asyncio.sleep(0.18)
    r.check("server emits ping frames", OPCODE_PING in opcodes_in(w.written),
            f"opcodes seen: {opcodes_in(w.written)}")

    b.note_client_seen(w)
    await asyncio.sleep(0.12)
    r.check("responsive client is not reaped",
            w in b.clients_by_screen.get(0, set()) and not w.closed)
    task.cancel()


async def test_idle_client_reaped(r):
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    b.KEEPALIVE_INTERVAL_S = 0.05
    b.CLIENT_IDLE_TIMEOUT_S = 0.10
    w = FakeWriter()
    await b.add(w, 0, "wallpaper")

    task = loop.create_task(b._keepalive_loop())
    await asyncio.sleep(0.45)
    r.check("silent client is reaped",
            w not in b.clients_by_screen.get(0, set()) and w.closed)
    task.cancel()


async def test_half_open_socket_reaped(r):
    """The core issue-#2 scenario as originally theorised: write()
    succeeds into the transport buffer but drain() raises. Without the
    await drain() in the keepalive, such a peer is invisible."""
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    b.KEEPALIVE_INTERVAL_S = 0.05
    b.CLIENT_IDLE_TIMEOUT_S = 10.0
    w = FakeWriter(fail_on_drain=True)
    await b.add(w, 0, "wallpaper")

    task = loop.create_task(b._keepalive_loop())
    await asyncio.sleep(0.2)
    r.check("half-open socket is detected and reaped",
            w not in b.clients_by_screen.get(0, set()) and w.closed)
    task.cancel()


async def test_broadcast_routing(r):
    """Frames must reach only the screen they're addressed to.

    smoke_test.py nominally covers this, but it runs against the live
    bridge, so a real SignalRGB instance broadcasting on screen 0
    pollutes the assertion — which is why it reports two failures on a
    perfectly healthy build. In-process there is no such interference.
    """
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    w0, w1 = FakeWriter(), FakeWriter()
    await b.add(w0, 0, "wallpaper")
    await b.add(w1, 1, "wallpaper")
    w0.written.clear()
    w1.written.clear()

    payload = bytes([1, 2, 3] * 4)
    await b.broadcast_frame(1, payload)

    got1 = [p for op, p in parse_server_frames(w1.written) if op == 0x2]
    got0 = [p for op, p in parse_server_frames(w0.written) if op == 0x2]
    r.check("target screen receives the frame", payload in got1,
            f"screen-1 binary payloads: {got1}")
    r.check("other screen receives nothing", not got0,
            f"screen-0 leaked: {got0}")


async def test_configurator_excluded_from_frames(r):
    """The Configurator drops binary frames anyway; sending them just
    burns heap in the user's tab."""
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    wp, cfg = FakeWriter(), FakeWriter()
    await b.add(wp, 0, "wallpaper")
    await b.add(cfg, 0, "configurator")
    wp.written.clear()
    cfg.written.clear()

    await b.broadcast_frame(0, bytes([9] * 12))
    cfg_binary = [p for op, p in parse_server_frames(cfg.written) if op == 0x2]
    wp_binary = [p for op, p in parse_server_frames(wp.written) if op == 0x2]
    r.check("wallpaper client gets the frame", bool(wp_binary))
    r.check("configurator is skipped", not cfg_binary,
            f"configurator got {len(cfg_binary)} binary frame(s)")


async def test_dead_writer_removed_on_broadcast(r):
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    dead = FakeWriter(fail_on_write=True)
    live = FakeWriter()
    await b.add(dead, 0, "wallpaper")
    await b.add(live, 0, "wallpaper")

    await b.broadcast_frame(0, bytes([1] * 12))
    r.check("writer that raises on write is dropped",
            dead not in b.clients_by_screen.get(0, set()))
    r.check("healthy writer survives", live in b.clients_by_screen.get(0, set()))


async def test_closing_transport_not_written(r):
    """A transport already closing must not be written to; pre-2.4.1
    this only surfaced as an exception, and after a resume a socket can
    linger in the closing state."""
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    w = FakeWriter()
    await b.add(w, 0, "wallpaper")
    w.transport.closing = True
    r.eq("_client_should_skip reports False for a closing transport",
         b._client_should_skip(w), False)


async def test_backpressure_skip(r):
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    w = FakeWriter()
    await b.add(w, 0, "wallpaper")

    w.transport.buffer_size = b._CLIENT_WRITE_BUFFER_LIMIT + 1
    r.check("over-buffered client is skipped", b._client_should_skip(w))

    w.transport.buffer_size = 0
    r.check("recovered client is written to again", not b._client_should_skip(w))
    r.check("skip counter resets on recovery", w not in b._client_skip_count)

    # A permanently stuck client must eventually be force-closed rather
    # than leaking its buffer forever (v2.2.2).
    w.transport.buffer_size = b._CLIENT_WRITE_BUFFER_LIMIT + 1
    for _ in range(b._SLOW_SKIP_FORCE_CLOSE_THRESHOLD + 1):
        b._client_should_skip(w)
    r.check("permanently stuck client is force-closed", w.transport.closing)


async def test_paused_suppresses_frames(r):
    loop = asyncio.get_running_loop()
    paused = {"v": True}
    b = make_broadcaster(bridge, loop, get_paused=lambda: paused["v"])
    w = FakeWriter()
    await b.add(w, 0, "wallpaper")
    w.written.clear()

    await b.broadcast_frame(0, bytes([1] * 12))
    r.check("no frames while paused",
            not [p for op, p in parse_server_frames(w.written) if op == 0x2])

    paused["v"] = False
    b._last_broadcast_per_screen.clear()  # bypass the rate cap for the test
    await b.broadcast_frame(0, bytes([1] * 12))
    r.check("frames resume after unpause",
            bool([p for op, p in parse_server_frames(w.written) if op == 0x2]))


async def test_unchanged_frames_not_resent(r):
    """v2.7.0-beta.9: a static colour in SignalRGB still arrives at 25-30
    frames/s; each one made the page re-blur the full-viewport canvas and
    DWM recompose the desktop (~4 % GPU, 0 of 250 frames differing)."""
    loop = asyncio.get_running_loop()
    b = make_broadcaster(bridge, loop)
    tapped = []
    b._frame_taps.append(lambda sc, p: tapped.append(p))
    w = FakeWriter()
    await b.add(w, 0, "wallpaper")
    w.written.clear()

    def sent():
        return [p for op, p in parse_server_frames(w.written) if op == 0x2]

    same = bytes([7] * 12)
    for _ in range(5):
        b._last_broadcast_per_screen.clear()   # bypass the rate cap
        await b.broadcast_frame(0, same)
    r.eq("five identical frames reach the page once", len(sent()), 1)
    r.eq("...but every one reaches the output taps (DMX needs a stream)",
         len(tapped), 5)

    b._last_broadcast_per_screen.clear()
    await b.broadcast_frame(0, bytes([40] * 12))
    r.eq("a clearly changed frame is sent at once", len(sent()), 2)

    # Keepalive: the same frame again once FRAME_KEEPALIVE_S has passed.
    last = b._frame_last[0]
    b._frame_last[0] = (last[0], last[1] - b.FRAME_KEEPALIVE_S - 0.01)
    b._last_broadcast_per_screen.clear()
    await b.broadcast_frame(0, bytes([40] * 12))
    r.eq("an unchanged frame is resent after the keepalive interval", len(sent()), 3)

    # v2.7.0-beta.10: a change too small to see waits (Neon Shift: 1-2/255).
    b._last_broadcast_per_screen.clear()
    await b.broadcast_frame(0, bytes([40] * 7 + [42] * 5))
    r.eq("a tiny change is held back", len(sent()), 3)
    b._last_broadcast_per_screen.clear()
    await b.broadcast_frame(0, bytes([40] * 7 + [44] * 5))
    r.eq("...also while it is still below the threshold", len(sent()), 3)
    b._last_broadcast_per_screen.clear()
    await b.broadcast_frame(0, bytes([40] * 7 + [47] * 5))
    r.eq("once it adds up to a visible step it goes out", len(sent()), 4)
    last = b._frame_last[0]
    b._frame_last[0] = (last[0], last[1] - b.FRAME_COALESCE_MAX_S - 0.01)
    b._last_broadcast_per_screen.clear()
    await b.broadcast_frame(0, bytes([40] * 7 + [48] * 5))
    r.eq("a tiny change goes out after FRAME_COALESCE_MAX_S at the latest",
         len(sent()), 5)
    b.coalesce_small_changes = False
    b._last_broadcast_per_screen.clear()
    await b.broadcast_frame(0, bytes([40] * 7 + [49] * 5))
    r.eq("switched off, every change goes out", len(sent()), 6)
    b.coalesce_small_changes = True
    # Stride 5 is coprime with 3: sampled bytes 0, 5, 10 of the pixel data
    # are R, B and G of different pixels, so no colour channel goes unseen.
    base = bytes(7 + 15)
    seen = []
    for k in (0, 5, 10):
        changed = bytearray(base)
        changed[7 + k] = 9
        seen.append((k % 3, bridge._frame_max_delta(base, bytes(changed))))
    r.check("the delta sample covers R, G and B",
            sorted(c for c, d in seen if d == 9) == [0, 1, 2], str(seen))

    # A page that connects now gets the next frame, not the next keepalive.
    w2 = FakeWriter()
    await b.add(w2, 0, "wallpaper")
    w2.written.clear()
    b._last_broadcast_per_screen.clear()
    await b.broadcast_frame(0, bytes([40] * 7 + [49] * 5))
    r.check("a new page gets the current frame immediately",
            bool([p for op, p in parse_server_frames(w2.written) if op == 0x2]))
    r.check("the keepalive interval is short of the page's 15 s no-frame check",
            b.FRAME_KEEPALIVE_S <= 2.0)


TESTS = [
    ("frame decoding", test_frame_decoding),
    ("add / remove lifecycle", test_add_and_remove),
    ("remove sweeps all screens", test_remove_sweeps_all_screens),
    ("remove is idempotent", test_remove_is_idempotent),
    ("keepalive pings", test_keepalive_pings),
    ("idle client reaped", test_idle_client_reaped),
    ("half-open socket reaped", test_half_open_socket_reaped),
    ("broadcast routing", test_broadcast_routing),
    ("unchanged frames not resent", test_unchanged_frames_not_resent),
    ("configurator excluded from frames", test_configurator_excluded_from_frames),
    ("dead writer removed on broadcast", test_dead_writer_removed_on_broadcast),
    ("closing transport not written", test_closing_transport_not_written),
    ("backpressure skip + force close", test_backpressure_skip),
    ("paused suppresses frames", test_paused_suppresses_frames),
]


async def main():
    r = Results("ws-lifecycle")
    for label, fn in TESTS:
        emit(f"\n{label}")
        await fn(r)
    emit("")
    return 0 if r.summary() else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
