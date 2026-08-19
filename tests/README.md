# Tests

```bash
python tests/run_all.py          # everything that runs without a bridge
python tests/run_all.py --live   # also drive a running SignalRGBBridge.exe
```

Exit code is 0 only if every suite passed. CI runs the first form on
every push and PR (`.github/workflows/smoke.yml`).

## What's here

| File | Covers |
|---|---|
| `test_ws_lifecycle.py` | Client registration, keepalive, reaping, broadcast routing, backpressure |
| `test_logging.py` | Log formatting, rotation, the resume marker, UDP progress throttling |
| `test_http_routing.py` | Which of the 32 routes answers what — dispatch decisions, not handler output |
| `test_version_order.py` | Update-checker version comparison — beta.9 must not outrank beta.10 |
| `test_port_override.py` | `SIGNALRGB_WP_PORT` — the override, its fallbacks, and that the CORS allowlist follows it |
| `test_language_setting.py` | The UI language picker — whitelist, validation, live re-resolve, and that the picker shows the preference |
| `test_standby_card.mjs` | The standby-card state machine — models `connect()` and proves the issue-#2 latch is gone |
| `test_wallpaper_source.mjs` | That the shipped `index.html` still contains those protections, and that its JS parses |
| `test_tint_colour.mjs` | `rgbToRgba` across hex / rgb() / rgba() input |
| `test_glripple.mjs` | The WebGL displacement path — `computeUV` against all six background-fit modes |
| `test_preset_parity.mjs` | All 17 ambient effects: that they run, paint, and match their Configurator preview |
| `test_span_apply.mjs` | Applying a library image to one half of a spanned screen keeps the other half |
| `test_plugin_grid.mjs` | SignalRGB plugin: per-device grid state — a settings change must reach every screen |
| `test_glow_spread.mjs` | The glow Spread slider: its labelling, and that `--glow` still only scales blur — never brightness |
| `test_filter_chain.mjs` | CSS `filter` collisions — an effect must never replace the glow's blur |
| `test_settings_reachable.mjs` | Characterisation for the redesign — every setting stays operable, every card sits in a real tab |
| `test_configurator_boots.mjs` | Runs the Configurator script in a sandbox — catches the beta.7 class of dead-page bug |
| `test_first_run_wizard.mjs` | Who the first-run wizard is shown to — and that picking a Look really applies it |
| `test_reimport_workshop.ps1` | Workshop-subscription detection and its exit codes |
| `test_release_tooling.ps1` | `release.ps1` preflight + the winget publish path |
| `harness.py` | Shared fakes and helpers (python) |
| `preset_harness.mjs` | Extracts and runs the two preset tables against a recording canvas |

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

## Characterisation before restructuring

`test_http_routing.py` was written to enable a change, not to catch a
bug. `handle_client` had grown to 1611 lines dispatching 32 routes
through a linear if/elif chain, and every HTTP request the bridge serves
goes through it. Splitting that up without a net would have been a
change whose mistakes are silent: the request still gets answered, by
the wrong handler.

So the tests came first and had to pass **unmodified against the code as
it was** — 52/52 before a single line moved. Only then was the split
made, and the same 52 had to stay green. A characterisation test that
needs adjusting to pass after the change has stopped characterising
anything.

It asserts dispatch decisions, not handler output: which route claims a
target, that `/config` still doesn't swallow `/configurator`, that a
wrong method 404s, and — most importantly — that the four routes which
deliberately *decline* after matching a prefix still fall through to the
routes behind them.

That last group is why the split signals "handled" by closing the
writer rather than returning a sentinel: the sentinel version would have
meant rewriting 55 bare `return` statements inside handler bodies,
several of them in nested helpers where `return` means something else.

## Run the code, don't read it

`test_preset_parity.mjs` started out matching regexes against the two
preset tables. That only worked for the presets whose alpha is a
literal (`const a = 0.34`); the other thirteen compute it, and
`a: 0.5 + Math.random()*0.3` is not something a regex can evaluate.
Those thirteen counted as passes. The suite reported 16/16 green while
covering four of seventeen effects — and could not detect the aurora
bug it had been written for.

It now extracts both tables and *runs* them against a recording canvas
(`preset_harness.mjs`), so the assertions are about what a preset
paints rather than how its source is spelled. That found two things a
regex never would: `storm` had been invisible to the old sweep entirely
(it is built by an IIFE, not an object literal), and `effectiveAlpha`
originally understood `rgba()` but not `hsla()` — which is what aurora
and plasma actually paint in, so every draw read as fully opaque.

Where the harness needs a helper the presets call, it lifts the real
function out of the source instead of reimplementing it. A local copy
of `rgbToRgba` here would be a third implementation of the thing whose
divergence this suite exists to catch.

## Adding a test

Regression tests belong here whenever a bug survives a release. The
pattern that worked for issue #2: reproduce the failure against the
*old* behaviour first (`test_standby_card.mjs` still does this
explicitly), then assert the fix. A test that only passes after the fix
doesn't prove it was ever testing the bug.

The cheap version of this, when the old behaviour is a constant: patch
it back in a scratch copy of the source and check the suite goes red.
Reverting aurora to 0.14 and plasma to 0.18 turns three checks in
`test_preset_parity.mjs` red — and it was that exercise, not the
original green run, that showed peak alpha alone is a poor visibility
signal and the tile/effect *ratio* had to carry the check.
