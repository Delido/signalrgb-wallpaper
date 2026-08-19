"""Run the whole test-suite.

    python tests/run_all.py            # everything that needs no bridge
    python tests/run_all.py --live     # also run smoke_test.py against a
                                       # running SignalRGBBridge.exe

Exit code is 0 only if every suite passed, so CI can gate on it.

The default set is deliberately hermetic: no bridge process, no ports, no
SignalRGB instance. smoke_test.py is the odd one out — it drives the real
bridge over a real socket, which makes it a genuine end-to-end check but
also means a live SignalRGB plugin broadcasting on screen 0 can fail it
for reasons that have nothing to do with the code. It stays opt-in.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

PY_SUITES = [
    ("WS lifecycle (python)", HERE / "test_ws_lifecycle.py"),
    ("Logging + diagnostics (python)", HERE / "test_logging.py"),
    ("HTTP routing (python)", HERE / "test_http_routing.py"),
    ("Version ordering (python)", HERE / "test_version_order.py"),
    ("Port override (python)", HERE / "test_port_override.py"),
    ("Language setting (python)", HERE / "test_language_setting.py"),
    ("Reset all screens (python)", HERE / "test_reset_all.py"),
]
JS_SUITES = [
    ("Standby card (node)", HERE / "test_standby_card.mjs"),
    ("Wallpaper source (node)", HERE / "test_wallpaper_source.mjs"),
    ("Tint colour helper (node)", HERE / "test_tint_colour.mjs"),
    ("glRipple WebGL path (node)", HERE / "test_glripple.mjs"),
    ("Preset parity (node)", HERE / "test_preset_parity.mjs"),
    ("Span half-apply (node)", HERE / "test_span_apply.mjs"),
    ("Setup status (node)", HERE / "test_setup_status.mjs"),
    ("Plugin grid state (node)", HERE / "test_plugin_grid.mjs"),
    ("Glow spread slider (node)", HERE / "test_glow_spread.mjs"),
    ("Glow filter chain (node)", HERE / "test_filter_chain.mjs"),
    ("Settings reachability (node)", HERE / "test_settings_reachable.mjs"),
    ("Configurator boots (node)", HERE / "test_configurator_boots.mjs"),
    ("First-run wizard (node)", HERE / "test_first_run_wizard.mjs"),
    ("Per-screen row counts (node)", HERE / "test_screen_count_rows.mjs"),
]
PS_SUITES = [
    ("Re-import / Workshop detection (pwsh)", HERE / "test_reimport_workshop.ps1"),
    ("Release + winget tooling (pwsh)", HERE / "test_release_tooling.ps1"),
]
LIVE_SUITES = [
    ("Smoke test — needs a running bridge", REPO / "wallpaper_bridge" / "smoke_test.py"),
]


def run(label, cmd, cwd):
    print(f"\n{'=' * 68}\n{label}\n{'=' * 68}", flush=True)
    # Merge the child's stderr into stdout and relay it: the python
    # suites deliberately report on stderr (bridge.py hijacks stdout on
    # import), and without this the detail is invisible in CI logs.
    proc = subprocess.run(cmd, cwd=str(cwd),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace")
    # Windows consoles default to cp1252, which cannot encode the arrows
    # and box characters the suites print. Re-encode per line rather than
    # letting one unprintable character abort the whole run.
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    for line in (proc.stdout or "").splitlines():
        if "module load failed" in line:
            continue  # optional integrations absent outside a full install
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)
    return proc.returncode == 0


def have(exe, *args):
    try:
        subprocess.run([exe, *args], capture_output=True, check=True)
        return True
    except Exception:
        return False


def have_node():
    return have("node", "--version")


def pwsh_exe():
    """PowerShell 7 if present, else the Windows-shipped 5.1. The
    installer scripts support both, so the tests should too."""
    for exe in ("pwsh", "powershell"):
        if have(exe, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"):
            return exe
    return None


def main():
    live = "--live" in sys.argv
    outcomes = []

    for label, path in PY_SUITES:
        outcomes.append((label, run(label, [sys.executable, str(path)], REPO)))

    if have_node():
        for label, path in JS_SUITES:
            outcomes.append((label, run(label, ["node", str(path)], REPO)))
    else:
        print("\nnode not found — skipping JS suites")
        outcomes.append(("JS suites", None))

    ps = pwsh_exe()
    if ps:
        for label, path in PS_SUITES:
            outcomes.append((label, run(label, [ps, "-NoProfile", "-File", str(path)], REPO)))
    else:
        print("\npowershell not found — skipping PS suites")
        outcomes.append(("PS suites", None))

    if live:
        for label, path in LIVE_SUITES:
            outcomes.append((label, run(label, [sys.executable, str(path)], REPO)))

    print(f"\n{'=' * 68}\nSUMMARY\n{'=' * 68}")
    failed = 0
    for label, ok in outcomes:
        if ok is None:
            print(f"  SKIP  {label}")
        elif ok:
            print(f"  PASS  {label}")
        else:
            print(f"  FAIL  {label}")
            failed += 1

    if not live:
        print("\n  (smoke_test.py skipped — pass --live with the bridge running)")
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
