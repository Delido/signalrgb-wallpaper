# Tests

```bash
python tests/run_all.py          # everything that runs without a bridge
python tests/run_all.py --live   # also drive a running SignalRGBBridge.exe
```

Exit code is 0 only if every suite passed. CI runs the first form on
every push and PR (`.github/workflows/tests.yml`).

## What's here

| File | Covers |
|---|---|
| `test_ws_lifecycle.py` | Client registration, keepalive, reaping, broadcast routing, backpressure |
| `test_standby_card.mjs` | The standby-card state machine — models `connect()` and proves the issue-#2 latch is gone |
| `test_wallpaper_source.mjs` | That the shipped `index.html` still contains those protections, and that its JS parses |
| `harness.py` | Shared fakes and helpers |

`wallpaper_bridge/smoke_test.py` stays where it is. It's the only
end-to-end check — real socket, real bridge — and runs opt-in via
`--live`.

## Design notes

**No pytest.** The suites run with a bare `python` / `node`, so anyone
who can build the project can run them without setting up a test
environment first.

**Nothing here needs a bridge process, a port, or SignalRGB.** That's
what makes them CI-viable and repeatable. `smoke_test.py` needs all
three, which is why it's separate.

**bridge.py replaces `sys.stdout` on import** (for the PyInstaller
`--noconsole` build). Test output therefore goes to stderr via
`harness.emit()`; `run_all.py` merges the streams back together.

**The JS tests come in pairs.** `test_standby_card.mjs` models the
connect/standby logic and verifies the model behaves; the model would
keep passing even if someone deleted the real thing, so
`test_wallpaper_source.mjs` greps `index.html` for the guards. Neither
is sufficient on its own.

## Why this exists

Issue #2 — a "bridge offline" card that latched on over a healthy
connection — took two releases to fix, and the first fix addressed a
failure mode that wasn't happening. Both the wrong theory and the right
one were settled in minutes once there was a harness to run them
against. That harness is now this directory.

`smoke_test.py` also used to report two failures on a healthy build:
it asserted "screen 0 received nothing" while a live SignalRGB plugin
was broadcasting on screen 0 at 30-60 Hz. It now filters for its own
synthetic payload, so the assertions mean what they say.

## Adding a test

Regression tests belong here whenever a bug survives a release. The
pattern that worked for issue #2: reproduce the failure against the
*old* behaviour first (`test_standby_card.mjs` still does this
explicitly), then assert the fix. A test that only passes after the fix
doesn't prove it was ever testing the bug.
