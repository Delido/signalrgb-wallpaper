"""SIGNALRGB_WP_PORT — the bridge's port must be overridable.

WHY THIS EXISTS

The port was a hard-coded 17320, so a second instance could not start:
it found the port taken, failed to bind, and exited without a window or
a message. On any machine with the bridge installed — which is every
developer machine — a freshly built EXE was therefore untestable. That
is not hypothetical: verifying the beta.14 build, every HTTP probe was
silently answered by the *installed* beta.13 still holding 17320, and
the new /health route read as a 404 "regression" that did not exist.

Two things have to hold, and the second is the one worth guarding:

  1. The override works, and bad values fall back rather than raise.
  2. The CORS / WS-Origin allowlist is derived from the overridden
     port. It is built from WS_PORT at import time, so a test instance
     must trust its own origin and no other. If someone later hard-codes
     17320 back into that list, a test instance would reject its own
     Configurator — or worse, keep trusting a port it no longer serves.

Each case runs in a fresh interpreter: the constants are module-level,
so re-importing in-process would not re-evaluate them.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import emit  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# Reports through a duplicated fd 2: bridge.py replaces sys.stdout AND
# sys.stderr on import, so an ordinary print here would vanish.
SNIPPET = (
    "import os, sys, pathlib\n"
    "REAL = os.dup(2)\n"
    "sys.path.insert(0, str(pathlib.Path('wallpaper_bridge').resolve()))\n"
    "sys.argv = ['bridge.py']\n"
    "import bridge\n"
    "out = '%d|%d|%s' % (bridge.WS_PORT, bridge.UDP_PORT,\n"
    "                    ','.join(sorted(bridge._ALLOWED_HTTP_ORIGINS)))\n"
    "os.write(REAL, out.encode())\n"
)

DEFAULT = 17320


def probe(value):
    """Import bridge.py with SIGNALRGB_WP_PORT set to `value`."""
    env = dict(os.environ)
    env.pop("SIGNALRGB_WP_PORT", None)
    if value is not None:
        env["SIGNALRGB_WP_PORT"] = value
    r = subprocess.run([sys.executable, "-c", SNIPPET], cwd=str(REPO),
                       capture_output=True, text=True, env=env)
    line = (r.stderr or "").strip().splitlines()
    if not line:
        raise AssertionError(f"no output; stdout={r.stdout!r} stderr={r.stderr!r}")
    ws, udp, origins = line[-1].split("|")
    return int(ws), int(udp), origins.split(",")


def main():
    passed = failed = 0

    def check(label, ok, detail=""):
        nonlocal passed, failed
        if ok:
            passed += 1
            emit(f"  ok    {label}")
        else:
            failed += 1
            emit(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))

    emit("\nSIGNALRGB_WP_PORT override\n" + "=" * 68)

    # --- the override itself ---
    ws, udp, _ = probe(None)
    check("no override -> 17320", ws == DEFAULT and udp == DEFAULT, f"got {ws}/{udp}")

    ws, udp, _ = probe("17399")
    check("valid port is honoured", ws == 17399 and udp == 17399, f"got {ws}/{udp}")

    # UDP and WS share a socket port; they must never diverge.
    check("UDP and WS stay in step", ws == udp, f"ws={ws} udp={udp}")

    # --- bad input falls back instead of raising ---
    for bad, why in [("abc", "not a number"),
                     ("", "empty"),
                     ("80", "below 1024, needs elevation"),
                     ("99999", "above 65535"),
                     ("-1", "negative"),
                     ("17399 ", "trailing space is tolerated")]:
        try:
            ws, udp, _ = probe(bad)
        except Exception as e:
            check(f"{bad!r} ({why}) does not crash the import", False, str(e))
            continue
        expect = 17399 if bad.strip() == "17399" else DEFAULT
        check(f"{bad!r} ({why}) -> {expect}", ws == expect, f"got {ws}")

    # --- the part that actually protects something ---
    _, _, origins = probe("17399")
    check("allowlist follows the overridden port",
          any("127.0.0.1:17399" in o for o in origins), str(origins))
    check("allowlist no longer trusts the default port",
          not any(f"127.0.0.1:{DEFAULT}" in o for o in origins), str(origins))
    check("localhost variant follows too",
          any(f"localhost:17399" in o for o in origins), str(origins))

    _, _, origins = probe(None)
    check("without override the allowlist is the default port",
          any(f"127.0.0.1:{DEFAULT}" in o for o in origins), str(origins))

    emit("\n" + "=" * 68)
    emit(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
