"""SignalRGB WebPipe load measurement (read-only).

A/B windows of SignalRGB's CPU (as % of the whole machine) while an extra
client reads the WebPipe one way or another, plus the frame-of-mind
numbers that decided v2.6/2.7 (msg rate, bytes, unsolicited traffic).

    python tools/webpipe_measure.py            # baseline vs full reader vs single getter
    python tools/webpipe_measure.py --secs 20

Rules (see the class docstring of SignalRgbWebPipePoller in bridge.py):
  * read-only: init (3), idle (4) and monitor.getValueByName only
  * the init reply contains the SignalRGB account (e-mail, uid): NEVER
    print it; this script prints counts, timings and sensor names only
  * the installed bridge keeps running and reading during the test, so
    every window includes its share; compare windows, not absolutes
"""
import argparse
import json
import pathlib
import select
import socket
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
import psutil  # noqa: E402
from harness import load_bridge  # noqa: E402

out = sys.__stdout__        # bridge.py replaces stdout on import


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=int, default=30)
    a = ap.parse_args()
    b = load_bridge()
    procs = [p for p in psutil.process_iter(["name"])
             if (p.info["name"] or "").lower() in ("signalrgb.exe", "signalrgbservice.exe")]
    if not procs:
        sys.exit("SignalRGB is not running")
    ncpu = psutil.cpu_count()

    def window(work=None):
        for p in procs:
            p.cpu_percent(None)
        t0 = time.time()
        while time.time() - t0 < a.secs:
            work() if work else time.sleep(0.5)
        return round(sum(p.cpu_percent(None) for p in procs) / ncpu, 2)

    P = b.SignalRgbWebPipePoller()

    def connect():
        s = socket.create_connection(("127.0.0.1", P.PORT), timeout=5)
        s.settimeout(15)
        P._handshake(s)
        return s

    res = {"A  baseline (installed bridge only)": window()}

    # Catalogue: names + getter index. Nothing from the reply is printed.
    s = connect()
    P._send_json(s, {"type": 3, "id": 0})
    init = P._recv_json(s, want_response_id=0)
    t0 = time.time()
    init_mb = len(json.dumps(init)) / 1e6
    P._load_init(init)
    del init
    stats = {"msgs": 0, "bytes": 0}

    def drain():
        P._send_json(s, {"type": 4})
        r, _, _ = select.select([s], [], [], 2.0)
        if r:
            m = P._recv_json(s)
            stats["msgs"] += 1
            stats["bytes"] += len(json.dumps(m))

    time.sleep(3)
    res["B  + full reader (init + drain)"] = window(drain)
    s.close()
    rate = "%.1f msg/s, %.0f KB/s" % (stats["msgs"] / a.secs, stats["bytes"] / a.secs / 1024)

    # Single mode: no init, 4 unique sensor names via the getter.
    counts = {}
    for f in P._sensors.values():
        counts[str(f.get("name"))] = counts.get(str(f.get("name")), 0) + 1
    names = [n for n, c in counts.items() if c == 1][:4]
    s = connect()
    req = [100]
    single = {"calls": 0, "unsolicited": 0, "max_ms": 0.0}
    last = [0.0]

    def getter():
        if time.time() - last[0] >= 1.0:
            last[0] = time.time()
            for n in names:
                req[0] += 1
                t = time.time()
                P._send_invoke(s, req[0], n)
                P._recv_reply(s, req[0])
                single["calls"] += 1
                single["max_ms"] = max(single["max_ms"], (time.time() - t) * 1000)
        r, _, _ = select.select([s], [], [], 0.1)
        if r:
            P._recv_json(s)
            single["unsolicited"] += 1

    time.sleep(3)
    res["C  + single getter x%d @1 Hz (no init)" % len(names)] = window(getter)
    s.close()
    time.sleep(3)
    res["A2 baseline again"] = window()

    out.write("init reply %.1f MB; full reader %s\n" % (init_mb, rate))
    out.write("single: %(calls)d calls, max %(max_ms).0f ms, %(unsolicited)d unsolicited msgs\n" % single)
    for k, v in res.items():
        out.write("%-42s %5.2f %% of machine\n" % (k, v))


if __name__ == "__main__":
    main()
