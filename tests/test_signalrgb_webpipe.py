"""SignalRGB WebPipe sensor source -- availability probing and protocol.

WHY THIS EXISTS

v2.6.0 reads hardware sensors from SignalRGB's own, undocumented
WebPipe (`ws://127.0.0.1:16036`, Qt QWebChannel) so users no longer need
LibreHardwareMonitor running beside it. The interface only exists in
recent SignalRGB versions, and the hard requirement was: CHECK whether it
works, never crash, and tell the user why it does not.

So most of this file is about the failure states, each reproduced by a
fake WebPipe server rather than assumed:

    unavailable / not_running   nothing listening (split by process list)
    incompatible                something listens but does not speak it,
                                or speaks it without a `monitor` object,
                                or never answers init
    monitoring_off              interface present, Monitoring switched off
    online                      sensors arriving

Plus the protocol properties that bit or would bite in practice:

  * the real init reply is 8.6 MB in 17 FRAGMENTS -- reassembly is
    mandatory, so the fake fragments too
  * property indices must come from the init reply, never be hard-coded
    -- the fake shifts them
  * the init reply carries the `user` object (e-mail, uid); none of it
    may reach the snapshot or the log
  * the interface accepts writes without auth; the client may only ever
    send init (3) and idle (4), and its frames must be masked
  * idle must go out after EVERY update: the server releases one message
    per idle, and the first version's 1 s throttle left CPU Load updating
    once in 15 s instead of at 1 Hz (measured live, SignalRGB 2.5.80)
"""

import base64
import hashlib
import json
import pathlib
import socket
import struct
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from harness import emit, load_bridge  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = (REPO / "wallpaper_bridge" / "bridge.py").read_text(encoding="utf-8")
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SECRET_MAIL = "secret.user@example.invalid"

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        emit(f"  ok    {label}")
    else:
        failed += 1
        emit(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


# ── fake server ─────────────────────────────────────────────────────────

# Sensor property layout as SignalRGB 2.5.80 ships it, and a shifted one.
REAL_LAYOUT = ["objectName", "uid", "name", "group", "value", "valueStr",
               "unit", "max", "min", "type", "history"]
SHIFTED_LAYOUT = ["history", "type", "min", "max", "unit", "valueStr",
                  "value", "group", "name", "uid", "objectName", "extra"]


def sensor_ref(oid, layout, **f):
    vals = {"objectName": "", "uid": f"{f['group']}:{f['name']}",
            "type": "LoadProvider", "history": {"seconds": [1, 2, 3]},
            "extra": None, "min": 0, "max": 100, **f}
    return {"__QObject*__": True, "id": oid,
            "data": {"methods": [], "signals": [],
                     "properties": [[i, n, ["sig", 1], vals.get(n)]
                                    for i, n in enumerate(layout)]}}


SENSORS = [
    dict(name="CPU Load", group="System", value=12.5, valueStr="12%", unit="%"),
    dict(name="CPU Temperature", group="Intel i9", value=61.3, valueStr="61°C", unit="C"),
    dict(name="Pump", group="Corsair", value=2789, valueStr="2789rpm", unit="rpm",
         max=3000),
    dict(name="CPU Fan", group="Mainboard", value=900, valueStr="900rpm", unit="rpm"),
    dict(name="CPU Fan", group="Mainboard", value=1100, valueStr="1100rpm", unit="rpm"),
    dict(name="GPU Clock", group="RTX", value=2610, valueStr="2610Mhz", unit="Mhz"),
]


def init_reply(layout=REAL_LAYOUT, monitor=True, sensors=SENSORS,
               disabled=False, pad=0):
    refs = [sensor_ref("{s%d}" % i, layout, **s) for i, s in enumerate(sensors)]
    data = {
        "user": {"properties": [[0, "email", [], SECRET_MAIL],
                                [1, "uid", [], "uid-should-not-leak"]]},
        "catalog": {"blob": "x" * pad},
    }
    if monitor:
        data["monitor"] = {"methods": [], "signals": [], "properties": [
            [0, "objectName", [], ""],
            [1, "sensors", ["sensorsChanged", 3], refs],
            [6, "monitoringDisabled", [], disabled],
        ]}
    return {"type": 10, "id": 0, "data": data}


class FakeWebPipe(threading.Thread):
    def __init__(self, mode="ok", layout=REAL_LAYOUT, frag=7, pad=0,
                 updates=None, **init_kw):
        super().__init__(daemon=True)
        self.mode, self.layout, self.frag, self.pad = mode, layout, frag, pad
        self.updates = list(updates or [])
        self.init_kw = init_kw
        self.received = []          # (opcode, masked, decoded JSON)
        self.connections = 0
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.port = self.srv.getsockname()[1]
        self.start()

    def run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self.serve, args=(c,), daemon=True).start()

    def close(self):
        try:
            self.srv.close()
        except OSError:
            pass

    @staticmethod
    def _frame(op, payload, fin=True):
        h = bytearray([(0x80 if fin else 0) | op])
        n = len(payload)
        if n < 126:
            h.append(n)
        elif n < 65536:
            h.append(126); h += struct.pack(">H", n)
        else:
            h.append(127); h += struct.pack(">Q", n)
        return bytes(h) + payload

    def send_msg(self, c, obj):
        raw = json.dumps(obj).encode()
        k = max(1, self.frag)
        size = max(1, -(-len(raw) // k))
        chunks = [raw[i:i + size] for i in range(0, len(raw), size)] or [b""]
        for i, ch in enumerate(chunks):
            op = 0x1 if i == 0 else 0x0
            c.sendall(self._frame(op, ch, fin=(i == len(chunks) - 1)))

    def recv_client(self, c):
        def ex(n):
            b = b""
            while len(b) < n:
                x = c.recv(n - len(b))
                if not x:
                    raise ConnectionError
                b += x
            return b
        b1, b2 = ex(2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", ex(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", ex(8))[0]
        masked = bool(b2 & 0x80)
        mask = ex(4) if masked else b"\0\0\0\0"
        data = bytes(x ^ mask[i % 4] for i, x in enumerate(ex(n)))
        try:
            obj = json.loads(data)
        except ValueError:
            obj = None
        self.received.append((b1 & 0x0F, masked, obj))
        return obj

    def serve(self, c):
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                head += c.recv(1024)
            if self.mode == "http":
                c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
                return
            key = [l.split(b":", 1)[1].strip() for l in head.split(b"\r\n")
                   if l.lower().startswith(b"sec-websocket-key")][0]
            acc = base64.b64encode(hashlib.sha1(key + GUID.encode()).digest())
            c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                      b"Connection: Upgrade\r\nServer: SignalRGB WebPipe\r\n"
                      b"Sec-WebSocket-Accept: " + acc + b"\r\n\r\n")
            self.recv_client(c)                          # init request
            if self.mode == "silent":
                time.sleep(5)
                return
            if self.mode == "garbage":
                c.sendall(self._frame(0x1, b"not json at all"))
                time.sleep(1)
                return
            c.sendall(self._frame(0x9, b"ping"))         # must be answered
            self.send_msg(c, init_reply(self.layout, pad=self.pad, **self.init_kw))
            while True:
                msg = self.recv_client(c)
                if msg is None or msg.get("type") != 4:
                    continue
                if self.updates:
                    self.send_msg(c, {"type": 2, "data": self.updates.pop(0)})
                else:
                    time.sleep(0.05)
        except (OSError, ConnectionError, IndexError):
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass


# ── helpers ─────────────────────────────────────────────────────────────

def make_poller(b, port, running=True, gate=True):
    P = b.SignalRgbWebPipePoller
    p = P(should_poll=(lambda: gate) if not callable(gate) else gate,
          port=port, process_info=lambda: (running, "2.5.80" if running else ""))
    p.READ_TIMEOUT_S = 1.0
    p.CONNECT_TIMEOUT_S = 1.0
    return p


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    b = load_bridge()
    logged = []
    b.print = lambda *a, **k: logged.append(" ".join(str(x) for x in a))

    emit("\nSignalRGB WebPipe -- availability states\n" + "=" * 68)

    # unavailable vs not_running: nothing listening, split by process list
    port = free_port()
    p = make_poller(b, port, running=True)
    p.probe_if_stale()
    check("nothing listening + SignalRGB running -> unavailable",
          p.get_status()["state"] == "unavailable", str(p.get_status()))
    p = make_poller(b, port, running=False)
    p.probe_if_stale()
    check("nothing listening + SignalRGB not running -> not_running",
          p.get_status()["state"] == "not_running", str(p.get_status()))
    check("an unavailable source contributes no sensors",
          p.get_snapshot() == {} and p.get_status()["online"] is False)

    for mode, kw, why in [
        ("http", {}, "port answers plain HTTP, no WebSocket upgrade"),
        ("silent", {}, "upgrade succeeds, init never answered"),
        ("garbage", {}, "init answered with non-JSON"),
        ("ok", {"monitor": False}, "no 'monitor' object (older SignalRGB)"),
    ]:
        srv = FakeWebPipe(mode=mode, **kw)
        p = make_poller(b, srv.port)
        t0 = time.time()
        p.probe_if_stale()
        st = p.get_status()
        check(f"incompatible: {why}", st["state"] == "incompatible",
              f"{st} -- must not read as 'too old' or 'not running'")
        check(f"  ...and it gives up instead of hanging ({time.time()-t0:.1f}s)",
              time.time() - t0 < 4.0)
        srv.close()

    srv = FakeWebPipe(disabled=True)
    p = make_poller(b, srv.port)
    p.probe_if_stale()
    check("Monitoring switched off -> monitoring_off",
          p.get_status()["state"] == "monitoring_off", str(p.get_status()))
    srv.close()
    srv = FakeWebPipe(sensors=[])
    p = make_poller(b, srv.port)
    p.probe_if_stale()
    check("empty sensor list -> monitoring_off, not online",
          p.get_status()["state"] == "monitoring_off")
    srv.close()

    emit("\nSignalRGB WebPipe -- protocol\n" + "=" * 68)

    # A multi-MB init in many fragments, with the real index layout.
    srv = FakeWebPipe(frag=17, pad=3 * 1024 * 1024)
    p = make_poller(b, srv.port)
    p.probe_if_stale()
    st, snap = p.get_status(), p.get_snapshot()
    check("fragmented multi-MB init is reassembled", st["state"] == "online",
          str(st))
    check("every sensor arrives", len(snap) == len(SENSORS), str(len(snap)))
    check("paths carry the SignalRGB prefix",
          "SignalRGB / System / CPU Load" in snap, str(list(snap)[:3]))
    check("repeated names get a stable ordinal",
          "SignalRGB / Mainboard / CPU Fan" in snap and
          "SignalRGB / Mainboard / CPU Fan #2" in snap)
    check("values are numeric", snap["SignalRGB / Corsair / Pump"]["value"] == 2789.0)
    check("units are normalised",
          snap["SignalRGB / Intel i9 / CPU Temperature"]["unit"] == "°C" and
          snap["SignalRGB / Corsair / Pump"]["unit"] == "RPM" and
          snap["SignalRGB / RTX / GPU Clock"]["unit"] == "MHz")
    check("the real scale travels with the value",
          snap["SignalRGB / Corsair / Pump"]["max"] == 3000)
    check("entries are tagged with their source",
          all(v["source"] == "signalrgb" for v in snap.values()))
    check("the server's ping was answered with a pong",
          any(op == 0xA for op, _, _ in srv.received))
    check("version is reported for display", st["version"] == "2.5.80")
    srv.close()

    # Shifted indices: everything must be looked up by NAME from the init.
    srv = FakeWebPipe(layout=SHIFTED_LAYOUT)
    p = make_poller(b, srv.port)
    p.probe_if_stale()
    snap = p.get_snapshot()
    check("property indices are read from the init, not hard-coded",
          snap.get("SignalRGB / System / CPU Load", {}).get("value") == 12.5,
          str(snap.get("SignalRGB / System / CPU Load")))
    srv.close()

    # Account data must go nowhere.
    blob = json.dumps(p.get_snapshot()) + json.dumps(p.get_status()) + "\n".join(logged)
    check("the user's e-mail never reaches snapshot, status or log",
          SECRET_MAIL not in blob)
    check("nor the account uid", "uid-should-not-leak" not in blob)

    # Live updates via the background loop, with shifted indices to
    # prove updates use the same name lookup. Several non-sensor updates
    # queue in front -- the reported starvation case.
    vi = str(SHIFTED_LAYOUT.index("value"))
    si = str(SHIFTED_LAYOUT.index("valueStr"))
    noise = [[{"object": "{lighting}", "properties": {"3": i}}] for i in range(6)]
    srv = FakeWebPipe(layout=SHIFTED_LAYOUT, updates=noise + [
        [{"object": "{s0}", "properties": {vi: 77.0, si: "77%"}}],
    ])
    p = make_poller(b, srv.port)
    p.start()
    t0 = time.time()
    ok = wait_for(lambda: p.get_snapshot().get(
        "SignalRGB / System / CPU Load", {}).get("value") == 77.0, 4.0)
    # Seven messages, one per idle. A 1 s idle throttle needs >= 7 s for
    # this; draining freely takes a fraction of a second.
    check("an update behind six unrelated ones still arrives promptly",
          ok and time.time() - t0 < 2.0,
          f"ok={ok} after {time.time()-t0:.1f}s -- idle must follow every "
          "message; throttling it starves sensors")
    p.stop()
    time.sleep(0.2)
    sent = list(srv.received)
    check("every client frame is masked", sent and all(m for _, m, _ in sent))
    types = {o.get("type") for op, _, o in sent if op == 0x1 and isinstance(o, dict)}
    check("the client only ever sends init and idle", types <= {3, 4},
          f"sent types {sorted(types)} -- the WebPipe accepts writes without auth")
    srv.close()

    # The guard itself, not just today's behaviour: a future call site
    # that tries invokeMethod / setProperty must be refused.
    class _Sink:
        def __init__(self): self.sent = b""
        def sendall(self, d): self.sent += d
    sink = _Sink()
    refused = []
    for t in (1, 6, 7, 9):
        try:
            p._send_json(sink, {"type": t})
            refused.append(False)
        except ValueError:
            refused.append(True)
    check("sending anything but init/idle is refused outright",
          all(refused) and sink.sent == b"", f"refused={refused}")
    check("the guard is not an assert (stripped under python -O)",
          'assert obj.get("type")' not in SRC)

    srv = FakeWebPipe(updates=[[{"object": "monitor", "properties": {"6": True}}]])
    p = make_poller(b, srv.port)
    p.start()
    ok = wait_for(lambda: p.get_status()["state"] == "monitoring_off", 4.0)
    check("switching Monitoring off live is noticed", ok, str(p.get_status()))
    check("...and its sensors stop being reported", p.get_snapshot() == {})
    p.stop()
    srv.close()

    # The gate: no widget placed -> no connection at all.
    srv = FakeWebPipe()
    p = make_poller(b, srv.port, gate=False)
    p.start()
    time.sleep(1.5)
    p.stop()
    check("no sensor widget placed -> the loop never connects",
          srv.connections == 0, f"{srv.connections} connections")
    # ...but the picker's one-shot probe does, once.
    p.probe_if_stale()
    p.probe_if_stale()
    check("the picker probe connects once and reuses a fresh result",
          srv.connections == 1 and p.get_status()["state"] == "online",
          f"{srv.connections} connections")
    srv.close()

    # Retry policy: a missing interface is not hammered every second.
    p = make_poller(b, free_port(), running=True, gate=True)
    p.start()
    time.sleep(1.5)
    p.stop()
    check("a missing interface backs off instead of retrying every second",
          p._next_attempt_ts - time.time() > 20)

    emit("\nSensorSources -- one list for the picker and the widget\n" + "=" * 68)

    class FakeLhm:
        def get_snapshot(self):
            return {"PC / CPU / Temperatures / Core": {"value": 50.0, "raw": "50 °C",
                                                       "unit": "°C"}}

        def get_status(self):
            return {"online": True, "sensorCount": 1, "lastError": "",
                    "lastPayloadBytes": 123}

    srv = FakeWebPipe()
    sig = make_poller(b, srv.port)
    src = b.SensorSources(FakeLhm(), sig)
    src.probe_if_stale()
    snap, st = src.get_snapshot(), src.get_status()
    check("both sources appear in one snapshot",
          "PC / CPU / Temperatures / Core" in snap and
          "SignalRGB / System / CPU Load" in snap)
    check("counts add up", st["sensorCount"] == 1 + len(SENSORS), str(st["sensorCount"]))
    check("legacy LHM fields survive for the picker",
          st["lastPayloadBytes"] == 123 and "lastError" in st)
    check("per-source status is reported",
          st["sources"]["signalrgb"]["state"] == "online" and
          st["sources"]["lhm"]["online"] is True)
    srv.close()
    check("SignalRGB alone is enough to be 'online'",
          b.SensorSources(None, sig).get_status()["online"] is True)

    emit("\nwiring\n" + "=" * 68)
    check("the runtime feeds the combined source to the picker",
          "self.broadcaster.hwmon_provider = self.sensor_sources" in SRC)
    check("...and to the sysstats push the widgets read",
          "hwmon=self.sensor_sources," in SRC)
    check("the poller is gated on a placed sensor widget",
          'SignalRgbWebPipePoller(\n            should_poll=self._poller_gate("hardware-sensor"))'
          in SRC)
    route = SRC[SRC.index("async def _route_hwmon_sensors"):
                SRC.index("async def _route_health")]
    check("the picker probe runs in an executor, not on the loop",
          "run_in_executor(None, probe)" in route,
          "a ~9 MB read on the event loop would freeze every page")
    check("health reports the probed state",
          '"signalrgb_sensors_state": sig_state' in SRC)

    emit("\nConfigurator explains every state\n" + "=" * 68)
    conf = (REPO / "wallpaper_bridge" / "configurator.html").read_text(encoding="utf-8")
    # The states are read from the poller's own source, so a state added
    # there without a sentence here fails -- the user would otherwise see
    # a raw i18n key exactly when something is wrong.
    poller = SRC[SRC.index("class SignalRgbWebPipePoller:"):SRC.index("class SensorSources:")]
    import re as _re
    states = set(_re.findall(r'(?:self\._state|state)\s*=\s*"(\w+)"', poller))
    states |= set(_re.findall(r'state, err = "(\w+)"', poller))
    states |= {"idle", "online"}
    check("the poller's states were found", {"unavailable", "not_running",
          "incompatible", "monitoring_off"} <= states, str(sorted(states)))
    cls_block = conf[conf.index("const SENSOR_STATE_CLASS = {"):]
    cls_block = cls_block[:cls_block.index("};")]
    for st in sorted(states):
        m = _re.search(r'"sensors\.sig\.' + st + r'":\s*\{\s*en:\s*"([^"]+)",\s*de:\s*"([^"]+)"', conf)
        check(f"state '{st}' has an English and a German sentence",
              bool(m) and m.group(1) != m.group(2), "missing or untranslated")
        check(f"state '{st}' has a status colour", (st + ":") in cls_block)
    check("the 'too old' sentence tells the user what to do",
          "update SignalRGB" in conf and "SignalRGB aktualisieren" in conf)
    check("the System tab renders the sensor line with the other status",
          "renderSensorSourceNote(h);" in conf)
    check("'Check' runs the bridge's one-shot probe",
          'fetch("/hwmon/sensors"' in conf[conf.index("function wireSensorCheck"):
                                           conf.index("function renderSetupStatus")])
    picker = conf[conf.index("function _buildSensorOptions"):
                  conf.index("function refreshHardwareSensorSchema")]
    # The condition must gate the assignment: naming the right words in
    # dead code (`if (false)`) passed the first version of this check.
    check("an empty picker says why SignalRGB has no sensors",
          "status.sources && status.sources.signalrgb" in picker and
          _re.search(r'if \(sig && sig\.state && sig\.state !== "online"\) \{\s*'
                     r'placeholder = t\("sensors\.picker_none",\s*'
                     r'\{ hint: sensorStateText\(sig\.state', picker) is not None,
          "the state check has to decide the placeholder")

    emit("\n" + "=" * 68)
    emit(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
