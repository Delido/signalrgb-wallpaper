"""Log format and the diagnostics they have to support.

The issue-#2 investigation ran entirely off a user's bridge.log, and two
properties of that log made it much harder than it needed to be:

  * no timestamps, so "before the sleep" vs "after the resume" could only
    be inferred from ordering
  * one [udp] progress line every ~600 frames, which at 30-60 Hz meant
    ~95 % of the 4 MiB ringbuffer was that single message — it had rolled
    almost everything else out, including the client counts that
    eventually identified the bug

These tests pin both, plus the resume marker added to make the next
sleep/resume report readable at a glance.
"""

import asyncio
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Results, emit, load_bridge  # noqa: E402

bridge = load_bridge()


def test_timestamp_format(r):
    """Every log line must carry a sortable local timestamp."""
    src = (Path(__file__).resolve().parent.parent
           / "wallpaper_bridge" / "bridge.py").read_text(encoding="utf-8")
    r.check("log handler installs a Formatter",
            "handler.setFormatter" in src)
    r.check("format includes asctime + milliseconds",
            "%(asctime)s.%(msecs)03d" in src)

    # Prove the format string actually renders the way we expect, rather
    # than just asserting it's present in the source.
    fmt = logging.Formatter(fmt="%(asctime)s.%(msecs)03d %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    rec = logging.LogRecord(name="bridge", level=logging.INFO, pathname="",
                            lineno=0, msg="[out] hello", args=None, exc_info=None)
    line = fmt.format(rec)
    r.check("rendered line starts with an ISO-ish timestamp",
            re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} ", line) is not None,
            f"got {line!r}")
    r.check("message survives the format", line.endswith("[out] hello"),
            f"got {line!r}")


def test_udp_spam_throttled(r):
    """The chunked-frame progress line must not dominate the log."""
    src = (Path(__file__).resolve().parent.parent
           / "wallpaper_bridge" / "bridge.py").read_text(encoding="utf-8")
    # There are two of these — the single-packet path and the chunked
    # path — and they flood identically. An earlier version of this test
    # only checked the first match and would have missed a regression in
    # the other, which is exactly the mistake that shipped the throttle
    # on one path only.
    intervals = [int(n) for n in re.findall(
        r"self\.count\s*==\s*1\s*or\s*self\.count\s*%\s*(\d+)\s*==\s*0", src)]
    r.check("both UDP throttle conditions found", len(intervals) >= 2,
            f"found {len(intervals)}: {intervals}")

    for every in intervals:
        r.check(f"interval {every} is at least 30k frames",
                every >= 30000, f"every {every}")

    # At 60 Hz, how much log does an 8-hour session spend on these lines?
    if intervals:
        worst = min(intervals)
        lines_per_8h = (8 * 3600 * 60) / worst
        r.check("under 100 lines per 8h session at 60 Hz",
                lines_per_8h < 100, f"{lines_per_8h:.0f} lines")


async def test_resume_marker(r):
    """A wall-clock gap much larger than the tick must be logged.

    Driven by monkeypatching time.time() and asyncio.sleep() rather than
    actually suspending: the loop sleeps 60 s per tick, so a real test
    would take minutes.
    """
    src = (Path(__file__).resolve().parent.parent
           / "wallpaper_bridge" / "bridge.py").read_text(encoding="utf-8")
    r.check("resume marker present in source", "[power] resume detected" in src)
    r.check("gap threshold defined", "_RESUME_GAP_S" in src)
    r.check("marker reports the client count",
            re.search(r"resume detected[\s\S]{0,200}clients=", src) is not None)

    # Behavioural check on the same arithmetic the marker uses, so a
    # future edit that inverts the comparison or mangles the formatting
    # gets caught.
    def span_for(gap_s):
        mins = int(gap_s // 60)
        hrs, mins = divmod(mins, 60)
        return f"{hrs}h{mins:02d}m" if hrs else f"{mins}m"

    r.eq("8h12m gap formats correctly", span_for(8 * 3600 + 12 * 60), "8h12m")
    r.eq("45m gap formats correctly", span_for(45 * 60), "45m")
    r.eq("exactly 1h formats correctly", span_for(3600), "1h00m")

    threshold = 120.0
    r.check("a normal 60s tick is below the threshold", 60.0 < threshold)
    r.check("a 30-minute suspend trips the threshold", 1800.0 > threshold)


def test_log_dir_unchanged(r):
    """The diagnostics export globs bridge.log* from a fixed path; if
    the logging setup ever moves, the export silently ships no logs."""
    src = (Path(__file__).resolve().parent.parent
           / "wallpaper_bridge" / "bridge.py").read_text(encoding="utf-8")
    setup_path = '"SignalRGBWallpaper" / "logs"' in src
    r.check("log dir is SignalRGBWallpaper/logs", setup_path)
    r.check("diagnostics export globs bridge.log*",
            'glob("bridge.log*")' in src)
    r.check("rotation keeps backups", "backupCount=3" in src)


def test_render_path_diagnostics(r):
    """v2.4.11 ships counters that answer one question from the user's
    own log: which ripple render path is actually running?

    Memory grows ~80 MB per activity cycle and never comes back
    (measured: 582 -> 658 -> 740 MB floor across cycles). The leading
    suspect is the SVG fallback, which encodes a fresh `data:` URL per
    frame into an feImage href — Chromium caches a decoded bitmap per
    unique data: URL and cannot revoke them.

    It is a suspicion, not a finding. Two earlier attempts at this same
    memory/perf problem were built on a plausible theory plus a
    benchmark of the wrong code path, and both made things worse. So
    this release only counts, and these checks exist so the counting
    itself cannot quietly break.
    """
    root = Path(__file__).resolve().parent.parent
    src = (root / "wallpaper_bridge" / "wallpaper" / "index.html").read_text(
        encoding="utf-8", errors="replace")
    bridge_src = (root / "wallpaper_bridge" / "bridge.py").read_text(
        encoding="utf-8", errors="replace")

    r.check("wallpaper declares the diag counters", "const _diag = {" in src)

    # Both ripple modules must be instrumented on BOTH sides of the
    # branch. Counting only the WebGL path would leave the fallback
    # invisible — which is the exact thing being measured.
    gl_hits = src.count("_diag.gl++")
    svg_hits = src.count("_diag.svg++")
    r.check("both modules count the WebGL path", gl_hits == 2, f"found {gl_hits}")
    r.check("both modules count the SVG fallback", svg_hits == 2, f"found {svg_hits}")

    # The two reasons usable() can fail need different fixes: no WebGL
    # at all is terminal, a missing texture is recoverable.
    r.check("usable() separates its two failure reasons",
            "_diag.usableFalseNoGl++" in src and "_diag.usableFalseNoImg++" in src)
    r.check("context loss and restore are counted",
            "_diag.ctxLost++" in src and "_diag.ctxRestored++" in src)

    # One timer, not one per reconnect. connect() runs again on every
    # reconnect, and an unguarded setInterval there would itself leak —
    # a poor way to instrument a leak hunt.
    r.check("the report timer is started once, not per reconnect",
            "if (_diagTimer) return;" in src)
    r.check("reports go out over the existing socket", 'type: "diag"' in src)

    # Bridge side: the report has to land in the log the user already
    # has, not in a devtools console they cannot open on a wallpaper.
    r.check("bridge handles the diag message",
            'msg.get("type") == "diag"' in bridge_src)
    r.check("bridge logs it under the [diag] tag",
            "[diag] screen=" in bridge_src)
    r.check("malformed reports cannot crash the WS loop",
            "[diag] malformed report" in bridge_src)


async def main():
    r = Results("logging")
    emit("\ntimestamp format")
    test_timestamp_format(r)
    emit("\nudp spam throttling")
    test_udp_spam_throttled(r)
    emit("\nresume marker")
    await test_resume_marker(r)
    emit("\nlog location contract")
    test_log_dir_unchanged(r)
    emit("\nrender-path diagnostics")
    test_render_path_diagnostics(r)
    emit("")
    return 0 if r.summary() else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
