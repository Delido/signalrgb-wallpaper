"""Characterisation tests for Broadcaster.handle_client's dispatch.

WHY THIS EXISTS

handle_client is 1611 lines — 13 % of bridge.py in a single function —
and dispatches 32 routes through a linear if/elif chain. Every HTTP
request the bridge serves goes through it: the Configurator, the
Builder, the library, the packs, the REST API, and the wallpaper page
itself.

The chain's correctness rests on an invariant that nothing enforces:
each block must `return` when it handles a request, and must NOT return
when it doesn't. Four blocks deliberately fall through —

    POST /screen/<N>/background   (falls through unless seg 3 is
    POST /screen/<N>/settings      "background" / "settings")
    GET  /wallpaper/...           (falls through to /plugins/ and /api/)
    GET  /plugins/...

— and issue #2 was a bug of exactly this shape: a `return` sitting
inside a loop it did not belong in.

These tests pin the current behaviour of the routing table so it can be
restructured without silently changing which handler answers what. They
assert the *dispatch decision*, not each handler's output: which route
claims a target, what a wrong method does, and that unknown paths 404.

Written before the restructure, run against the code as it is. A
characterisation test that only passes after a change proves nothing —
so these had to pass first, unmodified.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Results, emit, load_bridge, make_broadcaster  # noqa: E402

b = load_bridge()
R = Results("http routing")


class RecordingWriter:
    """A StreamWriter that captures the raw response bytes."""

    def __init__(self):
        self.written = bytearray()
        self.closed = False

    def write(self, data):
        self.written += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    def is_closing(self):
        return self.closed

    @property
    def text(self):
        return bytes(self.written).decode("latin1", "replace")

    @property
    def status(self):
        """First status line, e.g. 200 / 404 / 405, or None if silent."""
        if not self.written:
            return None
        first = self.text.split("\r\n", 1)[0]
        parts = first.split(" ")
        if len(parts) >= 2 and parts[0].startswith("HTTP"):
            try:
                return int(parts[1])
            except ValueError:
                return None
        return None


class ScriptedReader:
    """Feeds a fixed request; body reads return whatever is left."""

    def __init__(self, request: bytes, body: bytes = b""):
        self._request = request
        self._body = body

    async def readuntil(self, sep):
        return self._request

    async def readexactly(self, n):
        chunk, self._body = self._body[:n], self._body[n:]
        if len(chunk) < n:
            raise asyncio.IncompleteReadError(chunk, n)
        return chunk

    async def read(self, n=-1):
        chunk, self._body = self._body, b""
        return chunk


def request(method, target, headers=None, body=b""):
    """Build a raw HTTP/1.1 request head."""
    lines = [f"{method} {target} HTTP/1.1", "Host: 127.0.0.1:17320"]
    for k, v in (headers or {}).items():
        lines.append(f"{k}: {v}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin1"), body


def serve(method, target, headers=None, body=b""):
    """Run one request through handle_client, return the writer."""
    loop = asyncio.new_event_loop()
    try:
        bc = make_broadcaster(b, loop)
        head, payload = request(method, target, headers, body)
        w = RecordingWriter()
        loop.run_until_complete(
            bc.handle_client(ScriptedReader(head, payload), w))
        return w
    finally:
        loop.close()


# ── every declared route is reachable ────────────────────────────────────
#
# The failure this guards against is a route that stops being reachable
# because an earlier block widened its match — the /config vs
# /configurator case, where `startswith` would have eaten the latter.
# A route that answers is a route that still exists; what it answers
# with is the handler's business, not the dispatcher's.

emit("\nevery route still answers (i.e. is reachable in the chain)")
ROUTES = [
    ("GET", "/config"),
    ("GET", "/configurator"),
    ("GET", "/builder"),
    ("GET", "/widgets/skins"),
    ("GET", "/hwmon/sensors"),
    ("GET", "/openrgb/status"),
    ("GET", "/library/list"),
    ("GET", "/packs/list"),
    ("GET", "/backup"),
    ("GET", "/help"),
    ("GET", "/api/openapi.json"),
]
for method, target in ROUTES:
    w = serve(method, target)
    R.check(f"{method} {target} is dispatched (not 404)",
            w.status is not None and w.status != 404,
            f"status {w.status}")


# ── the /config vs /configurator distinction ─────────────────────────────
#
# Called out in a comment at the /config branch: matching with
# startswith would serve JSON in the Configurator's place. Both are
# live routes with different content types, so this is checkable rather
# than merely commented.

emit("\n/config and /configurator stay distinct")
cfg = serve("GET", "/config")
conf = serve("GET", "/configurator")
R.check("GET /config returns JSON",
        "application/json" in cfg.text.lower(), cfg.text[:80])
R.check("GET /configurator returns HTML",
        "text/html" in conf.text.lower(), conf.text[:80])
R.check("GET /config/ (trailing slash) also returns JSON",
        "application/json" in serve("GET", "/config/").text.lower())
R.check("GET /configurator/ (trailing slash) also returns HTML",
        "text/html" in serve("GET", "/configurator/").text.lower())


# ── query strings must not defeat matching ───────────────────────────────
#
# Most branches compare target.split("?", 1)[0]; a few use startswith on
# the raw target. Mixing the two is how a route starts ignoring its own
# query string.

emit("\na query string doesn't change which route answers")
for target in ("/config", "/configurator", "/library/list", "/packs/list"):
    plain = serve("GET", target)
    withq = serve("GET", target + "?screen=1&t=123")
    R.eq(f"GET {target} -> same status with and without a query",
         withq.status, plain.status)


# ── unknown paths reach the 404 at the end ───────────────────────────────

emit("\nunknown paths fall through to 404")
for target in ("/", "/nope", "/library", "/api", "/api/v2/status",
               "/configuratorX", "/configX"):
    w = serve("GET", target)
    R.eq(f"GET {target} -> 404", w.status, 404)


# ── method matters ───────────────────────────────────────────────────────
#
# Every branch tests the method as well as the path. A GET-only route
# reached by POST must fall through to the 404 rather than run.

emit("\nthe method is part of the match")
for method, target in [("POST", "/config"),
                       ("POST", "/configurator"),
                       ("POST", "/library/list"),
                       ("GET", "/library/upload"),
                       ("GET", "/library/pin"),
                       ("GET", "/restore"),
                       ("DELETE", "/config")]:
    w = serve(method, target)
    R.eq(f"{method} {target} -> 404 (wrong method)", w.status, 404)


# ── the fall-through blocks ──────────────────────────────────────────────
#
# The four blocks that intentionally do not return when their outer
# condition matches. These are the ones a restructure is most likely to
# break, because the bug is silent: the request still gets answered, by
# the wrong handler.

emit("\nPOST /screen/<N>/... falls through on an unknown third segment")
for target in ("/screen/0/nonsense", "/screen/0", "/screen/", "/screen/x/background"):
    w = serve("POST", target, {"Content-Length": "2"}, b"{}")
    R.eq(f"POST {target} -> 404 (no matching sub-route)", w.status, 404)

emit("\nPOST /screen/<N>/settings actually applies the settings")
if True:
    # This route was dead from the day it was written: the handler called
    # self.update_screen_setting, but that method lives on BridgeRuntime,
    # not Broadcaster — so every request raised AttributeError. It
    # predates the v2.4.4 route split (checked against the beta.4 tag)
    # and survived because the Configurator's "apply to all screens"
    # buttons are the only caller, and a failure there just looks like
    # the click not registering.
    #
    # The characterisation tests above could not catch it: they assert
    # which route answers, not that the handler runs. This one drives the
    # handler.
    class _Runtime:
        def __init__(self):
            self.applied = []

        def update_screen_setting(self, screen, key, value):
            self.applied.append((screen, key, value))
            return {"ok": True}

    body = b'{"gridRenderer": "canvas", "gridBlur": 24}'
    head = (b"POST /screen/0/settings HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n")

    loop = asyncio.new_event_loop()
    try:
        bc = make_broadcaster(b, loop)
        rt = _Runtime()
        bc.bridge_runtime = rt
        w = RecordingWriter()
        loop.run_until_complete(bc.handle_client(ScriptedReader(head, body), w))
        R.eq("POST /screen/0/settings -> 200", w.status, 200)
        R.check("both keys reached update_screen_setting",
                len(rt.applied) == 2, repr(rt.applied))
        R.check("the screen index is passed through",
                all(a[0] == 0 for a in rt.applied), repr(rt.applied))
        R.check("the response reports what was applied",
                '"applied": 2' in w.text, w.text[-60:])
    finally:
        loop.close()

    # Without a runtime wired up it must answer, not raise: a missing
    # collaborator is a 503, not a dropped connection.
    loop = asyncio.new_event_loop()
    try:
        bc = make_broadcaster(b, loop)
        w = RecordingWriter()
        crashed = False
        try:
            loop.run_until_complete(bc.handle_client(ScriptedReader(head, body), w))
        except Exception:
            crashed = True
        R.check("no runtime -> answers instead of raising", not crashed)
        R.check("no runtime -> 503", w.status == 503, f"status {w.status}")
    finally:
        loop.close()

emit("\nGET /health answers the setup question")
if True:
    # v2.4.11. get_health_status() has existed since v0.8.9 but was
    # reachable only from the tray's System-status dialog, which a
    # first-time user has no reason to open. Meanwhile the
    # Configurator's "connected" pill reports its own socket to the
    # bridge — which reads as "everything is fine" while the SignalRGB
    # half of the chain can be completely dead.
    #
    # The two fields added here are the two setup steps nothing
    # automates and nothing used to detect: the device never dragged
    # onto the SignalRGB canvas (frames_arriving), and the wallpaper
    # never assigned to a monitor (pages_per_screen).
    import json as _json

    class _Runtime:
        def __init__(self, **over):
            self.snap = {
                "plugin_present": True, "signalrgb_running": True,
                "frames_arriving": True, "screen_count": 2,
                "pages_per_screen": [1, 1], "fps_per_screen": [30.0, 30.0],
            }
            self.snap.update(over)

        def get_health_status(self):
            return dict(self.snap)

    def _health(**over):
        loop = asyncio.new_event_loop()
        try:
            bc = make_broadcaster(b, loop)
            bc.bridge_runtime = _Runtime(**over)
            w = RecordingWriter()
            head, _ = request("GET", "/health")
            loop.run_until_complete(bc.handle_client(ScriptedReader(head), w))
            parts = w.text.split("\r\n\r\n", 1)
            # Tolerate a non-JSON body rather than raising: if the route
            # is ever unhooked from the dispatcher the response is a 404
            # HTML page, and this helper has to let the assertions below
            # report that as a failure instead of dying here — which is
            # exactly what happened on the first mutation check.
            if len(parts) > 1 and parts[1]:
                try:
                    return w, _json.loads(parts[1])
                except ValueError:
                    return w, {}
            return w, {}
        finally:
            loop.close()

    w, data = _health()
    R.eq("GET /health -> 200", w.status, 200)
    R.check("responds with JSON", "application/json" in w.text.lower())
    R.check("reports every signal the tray dialog shows",
            all(k in data for k in ("plugin_present", "signalrgb_running",
                                    "frames_arriving", "pages_per_screen")),
            repr(sorted(data)))

    # The silent black-screen case: everything installed, device never
    # placed on the canvas. WS is up, so the standby card stays hidden
    # and the user gets no clue at all.
    _, data = _health(frames_arriving=False, fps_per_screen=[0.0, 0.0])
    R.check("a canvas-less SignalRGB shows as frames_arriving=false",
            data.get("frames_arriving") is False)

    # Per-screen, not a total — a total cannot say WHICH screen is
    # missing its wallpaper assignment.
    _, data = _health(pages_per_screen=[1, 0])
    R.check("unassigned screens are visible individually",
            data.get("pages_per_screen") == [1, 0], repr(data.get("pages_per_screen")))

    # A missing collaborator must answer, not raise.
    loop = asyncio.new_event_loop()
    try:
        bc = make_broadcaster(b, loop)
        w = RecordingWriter()
        head, _ = request("GET", "/health")
        crashed = False
        try:
            loop.run_until_complete(bc.handle_client(ScriptedReader(head), w))
        except Exception:
            crashed = True
        R.check("no runtime -> answers instead of raising", not crashed)
        R.check("no runtime -> reports unavailable rather than lying",
                '"available": false' in w.text)
    finally:
        loop.close()


emit("\n/wallpaper/ and /plugins/ fall through to the API block")
# Both are GET blocks that return only when they resolve a file. An
# unresolvable one must keep walking the chain rather than 404 early —
# which is observable: /api/openapi.json sits *after* them and still
# answers.
R.check("GET /api/openapi.json still answers despite earlier GET blocks",
        serve("GET", "/api/openapi.json").status == 200)
for target in ("/wallpaper/../bridge.py", "/wallpaper/nope.js",
               "/plugins/", "/plugins/nope/widget.html"):
    w = serve("GET", target)
    # Not "4xx": an unknown plugin answers 503 here because these tests
    # construct a Broadcaster without a plugin_registry, and the block
    # reports "registry not wired" before it can look anything up. That
    # is the honest response for the state the object is in. What must
    # hold is that nothing gets served as a file.
    R.check(f"GET {target} -> error, not a served file",
            w.status is not None and w.status >= 400, f"status {w.status}")


# ── path traversal stays refused ─────────────────────────────────────────
#
# The wallpaper and help-image blocks build filesystem paths from the
# target. Their rejection of traversal is a dispatch-level property, so
# it is pinned here too.

emit("\npath traversal is refused")
for target in ("/wallpaper/../../etc/passwd",
               "/wallpaper/..%2f..%2fbridge.py",
               "/help/images/../../bridge.py",
               "/library/thumb/../../bridge.py"):
    w = serve("GET", target)
    R.check(f"GET {target} is not served 200",
            w.status != 200, f"status {w.status}")


# ── a websocket upgrade never reaches the HTTP routes ────────────────────

emit("\nan Upgrade: websocket request leaves the HTTP chain immediately")
w = serve("GET", "/?screen=0", {"Upgrade": "websocket",
                                "Connection": "Upgrade",
                                "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="})
R.check("upgrade request is not answered with the 404 HTTP body",
        w.status != 404, f"status {w.status}")


# ── malformed requests don't crash the dispatcher ────────────────────────

emit("\nmalformed request lines are survivable")
for raw in [b"\r\n\r\n", b"GET\r\n\r\n", b"NONSENSE\r\n\r\n",
            b"GET  HTTP/1.1\r\n\r\n", b"\x00\x01\x02\r\n\r\n"]:
    loop = asyncio.new_event_loop()
    try:
        bc = make_broadcaster(b, loop)
        w = RecordingWriter()
        crashed = False
        try:
            loop.run_until_complete(bc.handle_client(ScriptedReader(raw), w))
        except Exception as e:
            crashed = True
            detail = f"{type(e).__name__}: {e}"
        R.check(f"{raw!r} handled without raising", not crashed,
                detail if crashed else "")
    finally:
        loop.close()


emit("")
sys.exit(0 if R.summary() else 1)
