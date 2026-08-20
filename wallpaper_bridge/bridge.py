"""
SignalRGB Desktop Wallpaper — bridge + tray + per-screen settings.

Single-process daemon with three concurrent jobs:

  1. asyncio loop (daemon thread)
        - UDP listener  :17320  (one datagram per frame from the plugin)
        - WebSocket fan-out :17320/?screen=N  (one route per monitor)
        - HTTP image proxy :17320/image?path=…  (CEF file:// workaround)
     Each datagram is tagged with a screen-index byte; matching WS clients
     get the raw datagram as a binary frame, others get nothing.
     On WS upgrade we also send the current per-screen settings as a JSON
     text frame so the page can apply background / layout / glow before
     the first paint.

  2. pystray tray icon (main thread, blocks on Win32 message pump)
        - Right-click menu: "Settings…", "Reload Config", "Quit"
        - "Settings…" pops a tkinter dialog with one tab per screen.
          Saving the dialog writes config.json AND pushes the new
          settings to all WS clients for that screen (live apply,
          no wallpaper reload).

  3. tkinter settings dialog (spawned per request, own thread)
        - Per-screen tab: background image picker, layout dropdown,
          glow / dim / blur sliders.

Config lives at %LOCALAPPDATA%\\SignalRGBWallpaper\\config.json.

Wire format (UDP, one frame per datagram):
  bytes 0..1   magic "SR"  (0x53 0x52)
  byte  2      screen index (u8)
  bytes 3..4   width  (u16 big-endian)
  bytes 5..6   height (u16 big-endian)
  bytes 7..    width*height RGB triplets, row-major
"""

from __future__ import annotations

import asyncio
import base64
import sys          # needed by the platform guard below, before the rest
import ctypes
if sys.platform == "win32":
    from ctypes import wintypes
else:
    # ctypes.wintypes raises ValueError at import time off Windows, so it
    # cannot sit at module scope unguarded — it would kill the process
    # before anything else runs. Everything that dereferences it is
    # already behind `if not _user32: return`, so a placeholder keeps the
    # module importable and the Win32 paths unreachable rather than
    # subtly wrong.
    wintypes = None  # type: ignore[assignment]
import hashlib
import copy
import json
import locale
import math
import mimetypes
import os
import random
import secrets
import re
import struct

# v1.4.0: OpenRGB output channel — talks to OpenRGB's network SDK
# (default localhost:6742) so the live wallpaper-glow colour stream
# also drives the user's OpenRGB-controlled hardware (RAM, fans,
# keyboard, …). See openrgb_client.py for the wire-protocol details.
try:
    from openrgb_client import OpenRGBClient as _OpenRGBClient
    from openrgb_client import OpenRGBError as _OpenRGBError
except Exception as _e:
    _OpenRGBClient = None
    _OpenRGBError = Exception   # so except clauses don't NameError
    print(f"[openrgb] client module load failed: {_e}")

# v1.6.2-beta: OpenRGB-SDK *server* — the inverse of the client above.
# Lets the bridge expose itself to the OpenRGB GUI as a set of virtual
# matrix devices (one per screen). Users can then apply any built-in
# OpenRGB effect (Rainbow Wave, Audio Visualizer, …) to the wallpaper
# without needing SignalRGB in the loop. Same try/except guard so a
# missing module downgrades the feature gracefully.
try:
    from openrgb_server import (
        OpenRgbSdkServer as _OpenRgbSdkServer,
        VirtualDevice as _OpenRgbVirtualDevice,
    )
except Exception as _e:
    _OpenRgbSdkServer = None
    _OpenRgbVirtualDevice = None
    print(f"[openrgb-sdk] server module load failed: {_e}")

# v1.5.0: sACN/E1.31 codec — used both by the outbound emitter (parallel
# to OpenRGB-output) and the inbound source manager (lets users drive
# the wallpaper glow from any sACN sender on their network). Wrapped
# in a try/except mirror of openrgb_client above so a missing module
# downgrades the feature gracefully instead of crashing the bridge.
try:
    import sacn_codec as _sacn
except Exception as _e:
    _sacn = None
    print(f"[sacn] codec module load failed: {_e}")

# v1.5.0-beta: MQTT 3.1.1 client for the HA / MQTT bridge.
try:
    from mqtt_client import MQTTClient as _MQTTClient
except Exception as _e:
    _MQTTClient = None
    print(f"[mqtt] client module load failed: {_e}")


def _redact_mqtt(d: dict) -> dict:
    """Copy of the mqttBridge config with `password` blanked. Used
    by Configurator pushes so a screenshot doesn't leak the broker
    credential; the real value stays only on disk + in the worker
    thread's `_connect` path."""
    out = dict(d or {})
    if out.get("password"):
        out["password"] = "***"
    return out
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from io import BytesIO
from pathlib import Path

# The tray icon and its tkinter dialogs are the only consumers of these
# four names, and every one of them lives in TrayApp / SettingsDialog /
# AboutDialog / SystemStatusDialog — nothing in the broadcaster, the
# runtime or the data plane touches them.
#
# On Windows they are always present and this is a plain import. On
# Linux they are a real system dependency (tkinter ships as python3-tk;
# pystray needs a GTK or X11 backend) and the port is meant to run
# headless anyway, so a missing GUI stack degrades to "no tray" instead
# of refusing to start. _HAS_TRAY lets main() make that decision
# explicitly rather than crashing 11 000 lines earlier.
try:
    import tkinter as tk
    from tkinter import filedialog, ttk
    import pystray
    from PIL import ImageTk
    _HAS_TRAY = True
    _TRAY_IMPORT_ERROR = None
except Exception as _tray_err:   # ImportError, or tkinter's TclError
    tk = filedialog = ttk = pystray = ImageTk = None  # type: ignore[assignment]
    _HAS_TRAY = False
    _TRAY_IMPORT_ERROR = _tray_err

from PIL import Image, ImageDraw

# psutil is optional at import time so a dev `python bridge.py` on a box
# without it still boots. When missing, the SysStats broadcaster simply
# stays disabled and the CPU / RAM / Net widgets render "n/a".
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    psutil = None
    _HAS_PSUTIL = False


def _setup_persistent_logging() -> None:
    """v1.2.13: route `print()` to a rotating log file in
    %LOCALAPPDATA%\\SignalRGBWallpaper\\logs so a `--noconsole`
    bundled bridge has a paper trail. Previously stdout/stderr were
    discarded by PyInstaller's `--noconsole` and the diagnostic
    export only captured snapshot state — when a user reported "the
    bridge died silently" there was nothing to read. Now every
    print() (and stderr write) lands in `bridge.log` with a single
    1 MiB ringbuffer + 3 backups (4 MiB total disk cap), and the
    diagnostics export folds it in.

    Best-effort: if the dir can't be created or the file can't be
    opened (permissions, disk full) we just keep the original
    sys.stdout / sys.stderr so the rest of the bridge still runs."""
    try:
        log_dir = Path(os.environ.get("LOCALAPPDATA",
                                      str(Path.home() / "AppData" / "Local"))) \
                  / "SignalRGBWallpaper" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "bridge.log"
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(
            log_path, maxBytes=1 * 1024 * 1024, backupCount=3,
            encoding="utf-8", delay=True,
        )
        # v2.4.3: stamp every line. Until now the log carried no time
        # information at all, which made the issue-#2 diagnosis far
        # harder than it needed to be: the reporter's bundle showed
        # what happened but not *when*, so "before the sleep" and
        # "after the resume" could only be guessed at from ordering.
        # Local time (not UTC) because these logs are read alongside a
        # user telling us "I woke it up around 7am".
        import logging as _lg
        handler.setFormatter(_lg.Formatter(
            fmt="%(asctime)s.%(msecs)03d %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        # Stream-like adapter so we can hand it to sys.stdout /
        # sys.stderr in place. Each print() lands as one record;
        # the handler does the rollover.
        class _LogStream:
            def __init__(self, h, level_tag):
                self._h = h
                self._tag = level_tag
                self._buf = ""
            def write(self, s):
                if not s: return 0
                self._buf += s
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    if line.strip():
                        import logging as _lg
                        rec = _lg.LogRecord(
                            name="bridge", level=_lg.INFO, pathname="",
                            lineno=0, msg=f"[{self._tag}] {line}",
                            args=None, exc_info=None,
                        )
                        try: self._h.emit(rec)
                        except Exception: pass
                return len(s)
            def flush(self):
                try: self._h.flush()
                except Exception: pass
            def isatty(self): return False
        sys.stdout = _LogStream(handler, "out")
        sys.stderr = _LogStream(handler, "err")
    except Exception:
        # Logging is a nice-to-have; if it fails we don't want to
        # take the bridge down with it.
        pass

_setup_persistent_logging()


def _resource_path(rel: str) -> Path:
    """Resolve a path that works both in dev runs and PyInstaller --onefile
    bundles. PyInstaller extracts bundled --add-data files into a temp dir
    pointed to by sys._MEIPASS; in dev the file sits next to bridge.py."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / rel
    return Path(__file__).parent / rel


# ============================================================================
# Fullscreen detection (Win32)
# ============================================================================

_user32 = ctypes.windll.user32 if sys.platform == "win32" else None


if wintypes is not None:
    class _MONITORINFO(ctypes.Structure):
        # _fields_ is evaluated when the class body runs, i.e. at import
        # time — so this is the second and last thing in the module that
        # a non-Windows interpreter cannot get past. Its only caller,
        # _is_fullscreen_active(), returns early when _user32 is None,
        # which is exactly the platforms where the name is absent.
        _fields_ = [
            ("cbSize",    wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork",    wintypes.RECT),
            ("dwFlags",   wintypes.DWORD),
        ]
else:
    _MONITORINFO = None  # type: ignore[assignment,misc]


def _is_fullscreen_active() -> bool:
    """True if the foreground window covers its entire monitor and isn't
    the shell/desktop. Catches both exclusive fullscreen and borderless-
    fullscreen games / video players. Cheap to call (a few syscalls)."""
    if not _user32:
        return False
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return False
        shell = _user32.GetShellWindow()
        if hwnd == shell:
            return False
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        hmon = _user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        if not hmon:
            return False
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        if not _user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return False
        return (rect.left   == mi.rcMonitor.left  and
                rect.top    == mi.rcMonitor.top   and
                rect.right  == mi.rcMonitor.right and
                rect.bottom == mi.rcMonitor.bottom)
    except Exception:
        return False


class FullscreenWatcher:
    """Polls _is_fullscreen_active() every second and fires a callback
    when the boolean flips. Runs on its own daemon thread; respects an
    `is_enabled` callable so the user's "pause on fullscreen" toggle in
    the tray can disable the feature without restarting the bridge."""

    def __init__(self, on_state_change, is_enabled):
        self._on = on_state_change   # callable(active: bool)
        self._enabled = is_enabled   # callable() -> bool
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="fullscreen-watcher")
        self._last = False

    def start(self):
        if self._thread.is_alive():
            return
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def is_paused(self) -> bool:
        return self._last

    def _run(self):
        while not self._stop.wait(1.0):
            try:
                if not self._enabled():
                    if self._last:
                        self._last = False
                        self._on(False)
                    continue
                current = _is_fullscreen_active()
                if current != self._last:
                    self._last = current
                    self._on(current)
            except Exception as e:
                print(f"[fullscreen] watch error: {e}")

# ============================================================================
# Update checker
# ============================================================================

UPDATE_API_URL          = "https://api.github.com/repos/Delido/signalrgb-wallpaper/releases"
UPDATE_RELEASES_HTML    = "https://github.com/Delido/signalrgb-wallpaper/releases"
UPDATE_CHECK_INTERVAL_S = 24 * 3600    # daily background poll
UPDATE_STARTUP_DELAY_S  = 12           # let the bridge settle before the first call


def _prerelease_key(pre: str) -> tuple:
    """Sort key for a prerelease label such as 'beta.11'.

    v2.4.4-beta.13: the label used to be compared as a plain string, so
    'beta.9' sorted ABOVE 'beta.10' — "9" > "1" character by character.
    From beta.10 onwards the tray offered beta.9 as the newest build and
    the real latest release was invisible.

    Semver says identifiers are compared field by field, numeric ones
    numerically and always below alphanumeric ones. Each field becomes
    (0, n, "") when it is a number and (1, 0, text) otherwise, which
    orders 9 < 10 < 11 and keeps 'beta' < 'rc' intact.
    """
    if not pre:
        return ()
    out = []
    for field in re.split(r"[.]", pre):
        if field.isdigit():
            out.append((0, int(field), ""))
        else:
            out.append((1, 0, field))
    return tuple(out)


def _parse_version(s: str) -> tuple:
    """Parse 'v0.5.1', '0.5.1' or '0.5.1-beta' into a sortable tuple.

    Stable releases sort *after* any prerelease of the same MAJOR.MINOR.PATCH,
    which matches semver semantics ('1.0.0-beta' < '1.0.0'). Returns
    (major, minor, patch, channel, pre_key) where channel is 1 for stable
    and 0 for prerelease. Garbage strings sort to (0,0,0,…) so they never
    trigger a false-positive 'newer than current' result for a real version.
    """
    s = (s or "").strip().lstrip("vV")
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-+](.+))?$", s)
    if not m:
        return (0, 0, 0, 0, ())
    major, minor, patch, pre = m.groups()
    return (int(major), int(minor), int(patch), 0 if pre else 1,
            _prerelease_key(pre or ""))


class UpdateChecker:
    """Polls the GitHub releases API once on startup (after a short delay)
    and once a day thereafter. Honours config flags:
      - updateCheckEnabled: master switch
      - allowBetas:         include prerelease tags in the comparison
    On detection of a newer version, calls on_update_available(tag, html_url).
    The tray menu queries available()/latest_url() between polls; check_now()
    triggers an immediate retry from the 'Check for updates now' menu entry."""

    def __init__(self, config: dict, config_lock: threading.Lock, on_update_available, on_check_done):
        self.config = config
        self.config_lock = config_lock
        self.on_update_available = on_update_available  # callable(tag, html_url)
        self.on_check_done = on_check_done              # callable(found: bool, error: str|None)
        self._stop = threading.Event()
        self._available_tag: str | None = None
        self._available_url: str | None = None
        # Direct download URL for the installer asset on the newer
        # release — lets the tray "Download + install" flow grab the
        # exe without re-querying the GitHub API.
        self._available_asset_url: str | None = None
        self._available_asset_size: int = 0
        self._last_checked_ts: float = 0.0
        self._last_error: str | None = None

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="update-checker").start()

    def stop(self):
        self._stop.set()

    # ── queried by the tray menu ────────────────────────────────────────
    def available(self) -> tuple[str, str] | None:
        if self._available_tag:
            return (self._available_tag, self._available_url or UPDATE_RELEASES_HTML)
        return None

    def available_asset(self) -> tuple[str, int] | None:
        """Direct URL + content-length for the newer release's installer
        asset, or None when no update is pending or the release didn't
        include an installer attachment."""
        if self._available_tag and self._available_asset_url:
            return (self._available_asset_url, self._available_asset_size)
        return None

    def last_checked(self) -> float:
        return self._last_checked_ts

    def last_error(self) -> str | None:
        return self._last_error

    def check_now(self):
        threading.Thread(target=self._safe_check, daemon=True, name="update-check-now").start()

    def download_and_install(self, on_progress=None, on_done=None) -> None:
        """Download the pending update's installer to %TEMP%, launch it
        silently with /VERYSILENT /SUPPRESSMSGBOXES, then exit the bridge
        so the installer can replace SignalRGBBridge.exe.

        on_progress(bytes_done, total_bytes) is called periodically.
        on_done(path | None, error | None) fires when the install spawn
        succeeds (path) or the flow aborts (error)."""
        threading.Thread(
            target=self._download_install_worker,
            args=(on_progress, on_done),
            daemon=True, name="update-install").start()

    def _download_install_worker(self, on_progress, on_done):
        asset = self.available_asset()
        if not asset:
            if on_done: on_done(None, "no installer asset on the latest release")
            return
        url, declared_size = asset
        try:
            tmp_dir  = Path(os.environ.get("TEMP", str(Path.home() / "AppData" / "Local" / "Temp")))
            tmp_dir.mkdir(parents=True, exist_ok=True)
            # Stamp the file with the version tag so a partial download
            # from a previous attempt doesn't masquerade as the new one.
            tag_clean = re.sub(r"[^A-Za-z0-9._-]", "", self._available_tag or "update")
            target = tmp_dir / f"SignalRGBWallpaperSetup-{tag_clean}.exe"
            if target.exists():
                try: target.unlink()
                except OSError: pass
            req = urllib.request.Request(
                url,
                headers={"User-Agent": f"SignalRGBWallpaper-Updater/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(target, "wb") as fp:
                total = int(resp.headers.get("Content-Length") or declared_size or 0)
                done = 0
                hasher = hashlib.sha256()
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    fp.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    if on_progress:
                        try: on_progress(done, total)
                        except Exception: pass
            local_sha256 = hasher.hexdigest()
            print(f"[update] downloaded {done:,} bytes → {target} (sha256={local_sha256})")
            # v2.2.2 anti-supply-chain check: each release publishes a
            # `<asset>.sha256` sidecar generated by installer\build.ps1
            # at the same time as the .exe. Fetch it, compare to what
            # we just hashed locally. If GitHub asset upload was
            # compromised, the .exe and the sidecar would need to be
            # tampered together AND by an attacker who has push
            # access to the release — strictly more work than swapping
            # the exe alone. Refuses to launch the installer on
            # mismatch / missing sidecar so a user who clicks "Update"
            # can't be silently downgraded to a malicious build.
            sidecar_url = url + ".sha256"
            try:
                sha_req = urllib.request.Request(
                    sidecar_url,
                    headers={"User-Agent": f"SignalRGBWallpaper-Updater/{APP_VERSION}"})
                with urllib.request.urlopen(sha_req, timeout=15) as sha_resp:
                    raw = sha_resp.read(256).decode("utf-8", errors="replace").strip()
            except Exception as e:
                try: target.unlink()
                except Exception: pass
                msg = (f"installer integrity check failed — no .sha256 "
                       f"sidecar at {sidecar_url} ({e}). Refusing to run "
                       f"an unverified installer; please report this and "
                       f"download the release manually.")
                print(f"[update] {msg}")
                if on_done: on_done(None, msg)
                return
            # Accept either a bare 64-char hex or the `sha256sum`
            # default format (`<hex>  <filename>`); take the first
            # token, lowercased.
            expected_sha256 = raw.split()[0].lower() if raw else ""
            if (len(expected_sha256) != 64
                    or any(c not in "0123456789abcdef" for c in expected_sha256)):
                try: target.unlink()
                except Exception: pass
                msg = (f"installer integrity check failed — .sha256 "
                       f"sidecar at {sidecar_url} did not parse as a "
                       f"sha256 hex digest (got {raw[:80]!r}).")
                print(f"[update] {msg}")
                if on_done: on_done(None, msg)
                return
            if expected_sha256 != local_sha256:
                try: target.unlink()
                except Exception: pass
                msg = (f"installer integrity check FAILED — downloaded "
                       f"sha256 {local_sha256} does not match published "
                       f"{expected_sha256}. Refusing to run; please "
                       f"report this immediately.")
                print(f"[update] {msg}")
                if on_done: on_done(None, msg)
                return
            print(f"[update] sha256 verified against {sidecar_url}")
        except Exception as e:
            print(f"[update] download failed: {e}")
            if on_done: on_done(None, str(e))
            return
        # Spawn the installer detached, then exit so it can replace our
        # exe. We use /SILENT (not /VERYSILENT) so the user sees an Inno
        # progress bar — they get visible confirmation the install is
        # really running, and any Inno error dialog is shown instead of
        # silently dropped. /SUPPRESSMSGBOXES still kills "are you sure?"
        # prompts. The bridge tray icon disappears; the installer's
        # [Run] section re-launches the new exe.
        #
        # Spawn strategy (Windows): use ShellExecuteW via ctypes rather
        # than subprocess.Popen with DETACHED_PROCESS, which had reports
        # of the spawned child dying together with the parent on some
        # Windows / SmartScreen configurations. ShellExecuteW goes
        # through the user shell so SmartScreen gets the right
        # provenance context and the child is a fully independent
        # process from the very first instruction.
        log_path = Path(os.environ.get("TEMP", str(Path.home() / "AppData" / "Local" / "Temp"))) / "signalrgb-update.log"
        def _log(line: str) -> None:
            try:
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
            except Exception:
                pass
        _log(f"download complete: {target} ({done:,} bytes)")
        # ── Auto-chain marker (v1.1.5+) ──
        # Drop a tiny marker file the newly-installed bridge picks up
        # on startup → triggers the wallpaper-bundle re-import once,
        # then deletes the marker. Removes the "two-click update"
        # friction (download+install, then re-import) so the user
        # just clicks once in the tray and both bridge + wallpaper
        # bundles refresh end-to-end.
        try:
            cfg_dir = Path(os.environ.get("LOCALAPPDATA",
                str(Path.home() / "AppData" / "Local"))) / "SignalRGBWallpaper"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            marker = cfg_dir / ".pending-reimport"
            marker.write_text(f"queued-at={time.time()}\n"
                              f"from-tag={self._available_tag or '?'}\n"
                              f"installer={target}\n", encoding="utf-8")
            _log(f"wrote re-import marker: {marker}")
        except Exception as e:
            _log(f"could not write re-import marker (non-fatal): {e}")
        launched = False
        try:
            if sys.platform == "win32":
                import ctypes
                # /MERGETASKS forces the auto-update installer to ALSO run
                # the host-bundle + plugin file-copy tasks. Without it,
                # `Flags: checkedonce` on those tasks defaults them OFF
                # during silent re-install — plugin / Lively ZIPs / WE
                # bundle would stay at the previous-install state.
                #
                # v1.7.2: `autostart` re-added. The v1.2.11 LoadLibrary
                # regression was caused by Inno's [Run] launching the
                # bridge via CreateProcess from the installer's process
                # context; the fix landed in
                # installer/signalrgb-wallpaper.iss by switching that
                # [Run] entry to the `shellexec` flag, which routes
                # the launch through ShellExecuteEx — the canonical
                # "as if launched from Explorer" path that gives the
                # bridge a fresh user-context token + the standard
                # shell DLL search path. Same mechanism our
                # `download_and_install` here already uses successfully
                # via ctypes ShellExecuteW. With that in place the
                # deferred-cmd relaunch hack we used to ship is gone —
                # no cmd, no fragile 40 s timeout, the installer itself
                # handles the bridge restart cleanly. Fixes the
                # "installer ran but new bridge never appeared" reports
                # from users whose AV or window manager killed the
                # standalone cmd-timeout window before it fired.
                #
                # autoinstall + openconfigurator deliberately omitted:
                # the former would re-download Lively every update,
                # the latter would pop a browser tab every update.
                mergetasks = (
                    "installplugin,"
                    "installlively,installlively\\autoimport,"
                    "installwallpaperengine,"
                    "autostart"
                )
                args = ('/SILENT /SUPPRESSMSGBOXES /NORESTART '
                        f'/MERGETASKS="{mergetasks}"')
                # nShowCmd=1 (SW_SHOWNORMAL) so the Inno progress
                # window is visible. ShellExecuteW returns >32 on
                # success; any value <=32 is a numeric error code.
                rc = ctypes.windll.shell32.ShellExecuteW(
                    None, "open", str(target), args, None, 1)
                _log(f"ShellExecuteW rc={rc}")
                if rc > 32:
                    launched = True
                else:
                    _log(f"ShellExecuteW failed (rc={rc}); falling back to subprocess")
            if not launched:
                import subprocess
                DETACHED_PROCESS = 0x00000008
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                subprocess.Popen(
                    [str(target),
                     "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                     f"/MERGETASKS={mergetasks}"],
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
                _log("subprocess.Popen fallback spawned")
                launched = True
            print(f"[update] installer spawned; exiting bridge to release file locks")
        except Exception as e:
            print(f"[update] installer spawn failed: {e}")
            _log(f"installer spawn failed: {e}")
            if on_done: on_done(None, str(e))
            return
        if on_done:
            try: on_done(str(target), None)
            except Exception: pass
        # v1.7.2: NO MORE deferred-cmd relaunch. Old flow spawned a
        # `cmd /c timeout 40 && start ""` window that survived our
        # process-exit thanks to CREATE_BREAKAWAY_FROM_JOB; users
        # reported the cmd window getting killed (by AV, by accidental
        # close, by window-manager edge cases) before its timeout
        # fired, leaving the installer's job done but no new bridge
        # running. Worse, the cmd flash was a visible 40-second hack
        # that looked unprofessional. Inno's [Run] entry now handles
        # the relaunch directly via `cmd /c start ""` (see the .iss);
        # `autostart` is back in MERGETASKS so the [Run] fires even
        # under silent /SILENT install.
        # Give the spawned installer a moment to grab its handles
        # before we kill the bridge process. Bumped from 1.5 s to 3 s
        # so AV real-time-scan of the just-downloaded exe has time to
        # complete before the parent process exits.
        time.sleep(3.0)
        _log("bridge exiting now (Inno [Run] entry will relaunch the new bridge)")
        # Hard-exit — graceful shutdown would let other threads block
        # the installer's overwrite of SignalRGBBridge.exe.
        os._exit(0)

    # ── internals ───────────────────────────────────────────────────────
    def _enabled(self) -> bool:
        with self.config_lock:
            return bool(self.config.get("updateCheckEnabled", True))

    def _allow_betas(self) -> bool:
        with self.config_lock:
            return bool(self.config.get("allowBetas", False))

    def _run(self):
        if self._stop.wait(UPDATE_STARTUP_DELAY_S):
            return
        while not self._stop.is_set():
            if self._enabled():
                self._safe_check()
            if self._stop.wait(UPDATE_CHECK_INTERVAL_S):
                return

    def _safe_check(self):
        try:
            self._check()
            self._last_error = None
            self.on_check_done(self._available_tag is not None, None)
        except Exception as e:
            self._last_error = str(e)
            print(f"[update] check failed: {e}")
            self.on_check_done(False, str(e))

    def _check(self):
        self._last_checked_ts = time.time()
        req = urllib.request.Request(UPDATE_API_URL, headers={
            "Accept":     "application/vnd.github+json",
            "User-Agent": f"SignalRGBWallpaper-Updater/{APP_VERSION}",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, list):
            raise RuntimeError("releases endpoint returned non-list payload")
        allow_betas = self._allow_betas()
        current = _parse_version(APP_VERSION)
        best: tuple = current
        best_tag = ""
        best_url = ""
        best_asset_url = ""
        best_asset_size = 0
        for rel in data:
            if not isinstance(rel, dict) or rel.get("draft"):
                continue
            if rel.get("prerelease") and not allow_betas:
                continue
            tag = rel.get("tag_name") or ""
            v = _parse_version(tag)
            if v > best:
                best = v
                best_tag = tag
                best_url = rel.get("html_url") or UPDATE_RELEASES_HTML
                # Find the installer asset on this release. Match by
                # the canonical filename prefix so we ignore zips,
                # source tarballs, and any future extra artefacts.
                assets = rel.get("assets") or []
                best_asset_url = ""
                best_asset_size = 0
                for a in assets:
                    if not isinstance(a, dict):
                        continue
                    name = (a.get("name") or "")
                    if (name.lower().startswith("signalrgbwallpapersetup")
                            and name.lower().endswith(".exe")):
                        best_asset_url  = a.get("browser_download_url") or ""
                        best_asset_size = int(a.get("size") or 0)
                        break
        if best > current:
            prev = self._available_tag
            self._available_tag        = best_tag
            self._available_url        = best_url
            self._available_asset_url  = best_asset_url or None
            self._available_asset_size = best_asset_size
            if prev != best_tag:    # only fire on first detection / new bump
                print(f"[update] newer release available: {best_tag} (current {APP_VERSION})")
                try: self.on_update_available(best_tag, best_url)
                except Exception as e: print(f"[update] notify failed: {e}")
        else:
            self._available_tag = None
            self._available_url = None
            self._available_asset_url = None
            self._available_asset_size = 0
            print(f"[update] no newer release; current {APP_VERSION} is up to date "
                  f"(allow_betas={allow_betas})")


# ============================================================================
# Constants
# ============================================================================

APP_NAME    = "SignalRGB Wallpaper Bridge"
APP_VERSION = "2.4.4-beta.22"

# v1.5.0-beta: the wallpaper-bundle code (wallpaper/index.html + its
# adjacent assets) is versioned INDEPENDENTLY of APP_VERSION. The
# bundle's "out of date" banner check uses this constant, NOT
# APP_VERSION — so a bridge-only release (like v1.4 / v1.5, both of
# which touched bridge.py + Configurator only) doesn't make every
# installed Lively / WE wallpaper bundle suddenly appear stale.
#
# When to bump WALLPAPER_VERSION:
#   • Any change to wallpaper/index.html, its JS, or its data shape
#   • Any change that requires re-uploading the WE Workshop item /
#     re-importing the Lively bundles
# When NOT to bump:
#   • Bridge-only features (new endpoints, new outputs, config
#     refactors, sources/sACN/OpenRGB plumbing, …)
#   • Configurator-only changes (configurator.html lives outside
#     the wallpaper bundle and ships only inside the bridge exe)
#
# Today: 1.3.0 is the last release that actually changed wallpaper
# code (the Matrix-render-pipeline rewrite + glass-tile / pause-GPU
# fixes from the v1.2.7..13 beta line, cut as 1.3.0). v1.4 + v1.5
# are bridge-only.
WALLPAPER_VERSION = "2.4.12"

# v1.2.13: WS protocol version. Sent on every settings push so a
# wallpaper page (or Configurator tab) loaded from an older bundle
# can detect a breaking change before it dispatches a malformed
# `widgets-set` / `quick-look-apply` etc. Bump when an existing
# message TYPE changes shape; new messages alone don't need a bump
# (the bridge drops unknown types silently). The version-mismatch
# banner v1.2.12 added is the user-visible companion.
WS_PROTOCOL_VERSION = 2

# v1.2.13: bumped CONFIG_VERSION (still defined below at module
# scope, where the persistence code lives) is the canonical
# config-schema marker — see _migrate_config() near load_config()
# for the actual migration steps. This comment-only constant is
# kept as documentation: any rename / shape change to an existing
# key requires bumping CONFIG_VERSION and adding a migration
# branch, not just a new setdefault().

# Diagnostic kill-switch retained from v1.2.9. When False the entire
# NowPlayingPoller / SMTC code path is removed at startup (no winrt
# import, no SMTCManager handle, no IPC). v1.2.10 re-enables it by
# default because the proper fix is the widget-aware idle-gate
# below — pollers now only run when a widget that consumes their
# data is actually placed somewhere. Flip to False to re-arm the
# diagnostic build for further debugging.
ENABLE_NOWPLAYING = True
APP_AUTHOR  = "Sebastian Mendyka"


# ─────────────────────────────────────────────────────────────────────────────
# v2.3.1: release-notes table for the Configurator's "What's new"
# modal. Each entry is a small dict {body_en, body_de} rendered as
# light Markdown (paragraphs split on blank lines, leading "- " or
# "• " becomes a real <li>, **bold** stays inline). Keep entries
# short and user-facing — full per-commit detail lives in CHANGELOG.md.
#
# The modal auto-fires once when the user's lastSeenAppVersion
# doesn't match APP_VERSION (post-update). A header button lets
# them re-open it later; "Open full changelog" jumps to the
# GitHub-hosted CHANGELOG.md.
#
# To add a new version: prepend an entry keyed by the bare version
# string ("2.4.0", not "v2.4.0"). _release_notes_for() falls back
# to a generic stub if a version isn't listed here yet.
# ─────────────────────────────────────────────────────────────────────────────
RELEASE_NOTES = {
    "2.4.4-beta.22": {
        "title_en": "What\'s new in v2.4.4-beta.22",
        "title_de": "Was ist neu in v2.4.4-beta.22",
        "body_en": (
            "**Fixed: System and Connections sat under a screen "
            "picker they have nothing to do with.**\n\n"
            "Both tabs are app-wide to the last control — the "
            "language, update checks, OpenRGB, sACN, MQTT and the "
            "API token are one setting each for the whole "
            "program. Showing *Screen 1 / Screen 2* above them "
            "implied screen 2 had its own, and that picking the "
            "right screen first mattered.\n\n"
            "The screen tabs are now hidden on those two, replaced "
            "by a line saying the settings are app-wide.\n\n"
            "**Also fixed: the widget layout preview** was never "
            "re-rendered when switching to the Content tab, so it "
            "could stay blank until something else nudged it. "
            "Left over from the tab rename in beta.16.\n\n"
            "**No re-import needed.**\n"
        ),
        "body_de": (
            "**Behoben: System und Verbindungen standen unter einer "
            "Bildschirm-Auswahl, mit der sie nichts zu tun "
            "haben.**\n\n"
            "Beide Tabs gelten bis zum letzten Regler für die ganze "
            "Anwendung — Sprache, Update-Prüfung, OpenRGB, sACN, "
            "MQTT und der API-Token sind jeweils eine einzige "
            "Einstellung. Die Anzeige *Bildschirm 1 / Bildschirm 2* "
            "darüber suggerierte, Bildschirm 2 hätte eigene Werte "
            "und man müsse vorher den richtigen auswählen.\n\n"
            "Die Bildschirm-Leiste wird dort jetzt ausgeblendet und "
            "durch einen Hinweis ersetzt.\n\n"
            "**Außerdem behoben: die Widget-Layout-Vorschau** wurde "
            "beim Wechsel auf den Inhalte-Tab nie neu gezeichnet und "
            "konnte leer bleiben. Ein Überbleibsel der "
            "Tab-Umbenennung aus Beta 16.\n\n"
            "**Kein Neuimport nötig.**\n"
        ),
    },
    "2.4.4-beta.21": {
        "title_en": "What\'s new in v2.4.4-beta.21",
        "title_de": "Was ist neu in v2.4.4-beta.21",
        "body_en": (
            "**New: Reset all screen settings.**\n\n"
            "System tab, at the bottom. Puts background, glow, "
            "effects and widgets back to defaults on every screen "
            "at once — the way out when a setup has been fiddled "
            "with beyond repair.\n\n"
            "**It keeps the things that are laborious to "
            "recreate:** your preset slots, per-app profiles, the "
            "image library, and every option in the System tab "
            "itself (language, updates, OpenRGB, sACN, MQTT).\n\n"
            "A copy of your configuration is saved next to it "
            "first, named config.before-reset-<date>.json, so a "
            "misclick is recoverable.\n\n"
            "Resetting a single screen is still available from that "
            "screen's own card.\n\n"
            "**No re-import needed.**\n"
        ),
        "body_de": (
            "**Neu: Alle Bildschirm-Einstellungen zurücksetzen.**\n\n"
            "Im System-Tab ganz unten. Setzt Hintergrund, Glow, "
            "Effekte und Widgets auf allen Bildschirmen auf einmal "
            "zurück — der Ausweg, wenn eine Konfiguration "
            "verbastelt ist.\n\n"
            "**Erhalten bleibt, was mühsam wiederherzustellen "
            "wäre:** deine Voreinstellungs-Slots, App-Profile, die "
            "Bildbibliothek und alle Optionen im System-Tab selbst "
            "(Sprache, Updates, OpenRGB, sACN, MQTT).\n\n"
            "Vorher wird eine Kopie deiner Konfiguration daneben "
            "abgelegt, benannt config.before-reset-<Datum>.json — "
            "ein Fehlklick lässt sich also rückgängig machen.\n\n"
            "Einen einzelnen Bildschirm zurückzusetzen geht "
            "weiterhin über dessen eigene Karte.\n\n"
            "**Kein Neuimport nötig.**\n"
        ),
    },
    "2.4.4-beta.20": {
        "title_en": "What\'s new in v2.4.4-beta.20",
        "title_de": "Was ist neu in v2.4.4-beta.20",
        "body_en": (
            "**Fixed: per-screen lists only ever showed one "
            "screen.**\n\n"
            "With two or more screens, *Colour source per screen*, "
            "the sACN universe list and the OpenRGB source picker "
            "each showed a single row — so the second screen could "
            "not be configured at all.\n\n"
            "All four read the screen count from the wrong place "
            "and quietly fell back to 1. Nothing errored, which is "
            "why it lasted several releases: one row looks like a "
            "deliberate default rather than a wrong answer.\n\n"
            "**No re-import needed.**\n"
        ),
        "body_de": (
            "**Behoben: Pro-Bildschirm-Listen zeigten immer nur "
            "einen Bildschirm.**\n\n"
            "Bei zwei oder mehr Bildschirmen zeigten *Farbquelle pro "
            "Bildschirm*, die sACN-Universen und die "
            "OpenRGB-Quellenauswahl jeweils nur eine Zeile — der "
            "zweite Bildschirm ließ sich dort also gar nicht "
            "einstellen.\n\n"
            "Alle vier lasen die Bildschirmanzahl an der falschen "
            "Stelle und fielen still auf 1 zurück. Es gab keinen "
            "Fehler — deshalb blieb es über mehrere Versionen "
            "unbemerkt: Eine Zeile sieht wie eine gewollte "
            "Voreinstellung aus, nicht wie ein falsches Ergebnis.\n\n"
            "**Kein Neuimport nötig.**\n"
        ),
    },
    "2.4.4-beta.19": {
        "title_en": "What\'s new in v2.4.4-beta.19",
        "title_de": "Was ist neu in v2.4.4-beta.19",
        "body_en": (
            "**New: you can pick the language.**\n\n"
            "System tab, right at the top: *Automatic*, English or "
            "Deutsch. Automatic follows your Windows language, "
            "which is what happened before — there was simply no "
            "way to override it.\n\n"
            "The change applies immediately. No restart.\n\n"
            "Everything else was already in place: the setting has "
            "been in the config file for many versions and both "
            "translations were complete. The only missing piece was "
            "a control to write it, so choosing a language meant "
            "editing config.json by hand.\n\n"
            "**No re-import needed.**\n"
        ),
        "body_de": (
            "**Neu: Du kannst die Sprache auswählen.**\n\n"
            "Im System-Tab ganz oben: *Automatisch*, English oder "
            "Deutsch. Automatisch richtet sich nach deiner "
            "Windows-Sprache — genau das passierte auch vorher "
            "schon, nur ließ es sich nicht ändern.\n\n"
            "Die Änderung wirkt sofort. Kein Neustart nötig.\n\n"
            "Alles Übrige war längst vorhanden: Die Einstellung "
            "steht seit vielen Versionen in der Konfigurationsdatei, "
            "und beide Übersetzungen sind vollständig. Es fehlte nur "
            "die Bedienmöglichkeit — die Sprache zu wechseln hieß "
            "bisher, config.json von Hand zu bearbeiten.\n\n"
            "**Kein Neuimport nötig.**\n"
        ),
    },
    "2.4.4-beta.18": {
        "title_en": "What\'s new in v2.4.4-beta.18",
        "title_de": "Was ist neu in v2.4.4-beta.18",
        "body_en": (
            "**Fixed: the four tab names stayed English.**\n\n"
            "On a German UI the navigation still read Appearance, "
            "Content, Connections, System while everything around "
            "it was translated.\n\n"
            "The tab labels were written once when the navigation "
            "was built, before the language was known, and were "
            "never refreshed afterwards. The bug is older than the "
            "redesign — it simply could not be seen while the tabs "
            "were called Look, Widgets and System, which are spelled "
            "the same in German.\n\n"
            "**Also: two German texts that were half-translated** "
            "have been rewritten — the Quick Looks description and "
            "the screen-layout hint.\n\n"
            "**No re-import needed.**\n"
        ),
        "body_de": (
            "**Behoben: Die vier Tab-Namen blieben englisch.**\n\n"
            "Bei deutscher Oberfläche stand in der Navigation "
            "weiterhin Appearance, Content, Connections, System, "
            "während drumherum alles übersetzt war.\n\n"
            "Die Beschriftungen wurden einmalig beim Aufbau der "
            "Navigation gesetzt — bevor die Sprache feststand — und "
            "danach nie wieder aktualisiert. Der Fehler ist älter als "
            "der Umbau: Solange die Tabs Look, Widgets und System "
            "hießen, fiel er nicht auf, weil sich diese Wörter im "
            "Deutschen nicht unterscheiden.\n\n"
            "**Außerdem: zwei halb übersetzte deutsche Texte** wurden "
            "neu formuliert — die Beschreibung der Quick Looks und "
            "der Hinweis zum Bildschirm-Layout.\n\n"
            "**Kein Neuimport nötig.**\n"
        ),
    },
    "2.4.4-beta.17": {
        "title_en": "What\'s new in v2.4.4-beta.17",
        "title_de": "Was ist neu in v2.4.4-beta.17",
        "body_en": (
            "**Fixed: an empty box under the System card.**\n\n"
            "Reorganising the Configurator in beta.16 cut through "
            "the middle of a collapsible section, which left the "
            "browser rendering an empty expandable strip with "
            "nothing in it.\n\n"
            "The OpenRGB block it belonged to is back where it "
            "should be, under Connections.\n\n"
            "**No re-import needed.**\n"
        ),
        "body_de": (
            "**Behoben: ein leerer Kasten unter der System-Karte.**\n\n"
            "Beim Umbau des Konfigurators in Beta 16 verlief der "
            "Schnitt mitten durch einen aufklappbaren Abschnitt. "
            "\u00dcbrig blieb ein leerer Aufklapp-Streifen ohne Inhalt.\n\n"
            "Der zugeh\u00f6rige OpenRGB-Block steht wieder dort, wo er "
            "hingeh\u00f6rt: unter Verbindungen.\n\n"
            "**Kein Neuimport n\u00f6tig.**\n"
        ),
    },
    "2.4.4-beta.16": {
        "title_en": "What\'s new in v2.4.4-beta.16",
        "title_de": "Was ist neu in v2.4.4-beta.16",
        "body_en": (
            "**The Configurator has been reorganised.**\n\n"
            "Six tabs named after the machinery — Look, Library, "
            "Effects, Widgets, Integrations, System — have become "
            "four named after what you want to do: **Appearance**, "
            "**Content**, **Connections**, **System**.\n\n"
            "**Nothing was removed.** Every setting is still there "
            "and your saved presets, profiles and Quick Looks are "
            "unchanged. Settings most people never touch now sit "
            "behind a *More settings* link inside each card, which "
            "stays open once you open it.\n\n"
            "**New: a first-run setup.** On a fresh install the "
            "Configurator now walks you through picking a look and a "
            "background, so you end up with a working wallpaper "
            "instead of an explained blank screen. The old tour is "
            "still there — the *Tour* button in the header.\n\n"
            "**Fixed: pill height and width were missing.** Both "
            "have worked for a long time and were adjustable from "
            "the tray, but the Configurator never had sliders for "
            "them. They are in the Glow card under *More settings*.\n\n"
            "**Fixed: a dead step in the tour**, which pointed at a "
            "card in a tab that never showed it.\n\n"
            "**No re-import needed** — the wallpaper itself is "
            "unchanged since beta.15.\n"
        ),
        "body_de": (
            "**Der Konfigurator wurde neu geordnet.**\n\n"
            "Aus sechs Tabs, die nach der Technik benannt waren — "
            "Look, Bibliothek, Effekte, Widgets, Integrationen, "
            "System — sind vier geworden, die danach benannt sind, "
            "was du vorhast: **Aussehen**, **Inhalte**, "
            "**Verbindungen**, **System**.\n\n"
            "**Es wurde nichts entfernt.** Alle Einstellungen sind "
            "weiterhin da, und deine gespeicherten Voreinstellungen, "
            "Profile und Quick Looks bleiben unver\u00e4ndert. Was die "
            "meisten nie anfassen, liegt jetzt hinter einem Link "
            "*Mehr Einstellungen* in der jeweiligen Karte — einmal "
            "ge\u00f6ffnet, bleibt er offen.\n\n"
            "**Neu: eine Ersteinrichtung.** Bei einer frischen "
            "Installation f\u00fchrt dich der Konfigurator jetzt durch die "
            "Wahl eines Looks und eines Hintergrunds. Am Ende hast du "
            "ein fertiges Wallpaper statt eines erkl\u00e4rten schwarzen "
            "Bildschirms. Die alte Tour gibt es weiterhin — \u00fcber den "
            "*Tour*-Knopf oben.\n\n"
            "**Behoben: Pillen-H\u00f6he und -Breite fehlten.** Beide "
            "funktionieren seit Langem und waren \u00fcber das Tray "
            "einstellbar, aber im Konfigurator gab es keine Regler "
            "daf\u00fcr. Sie stehen jetzt in der Glow-Karte unter *Mehr "
            "Einstellungen*.\n\n"
            "**Behoben: ein toter Schritt in der Tour**, der auf eine "
            "Karte zeigte, die der gew\u00e4hlte Tab nie anzeigt.\n\n"
            "**Kein Neuimport n\u00f6tig** — das Wallpaper selbst ist "
            "seit Beta 15 unver\u00e4ndert.\n"
        ),
    },
    "2.4.4-beta.15": {
        "title_en": "What\'s new in v2.4.4-beta.15",
        "title_de": "Was ist neu in v2.4.4-beta.15",
        "body_en": (
            "**Fixed: Liquid Distortion made the glow look blocky.**\n\n"
            "Switching Liquid Distortion on stripped the glow layer of "
            "its blur, so the individual squares of the glow grid "
            "showed as hard blocks. Switching it off brought the blur "
            "back.\n\n"
            "A CSS quirk: the distortion and the glow blur are the "
            "same property, so the distortion *replaced* the blur "
            "instead of adding to it. Both are now applied together.\n\n"
            "This only ever affected the fallback rendering path. If "
            "your graphics driver supports the faster path, you never "
            "saw it.\n\n"
            "**Re-import needed** — the wallpaper itself changed. In "
            "Lively, remove the wallpaper and import the new zip; in "
            "Wallpaper Engine, re-subscribe or re-import the bundle.\n"
        ),
        "body_de": (
            "**Behoben: Die Fl\u00fcssige Verzerrung lie\u00df den Glow "
            "kl\u00f6tzig aussehen.**\n\n"
            "Beim Aktivieren der Fl\u00fcssigen Verzerrung verlor die "
            "Glow-Schicht ihre Weichzeichnung, sodass die einzelnen "
            "K\u00e4stchen des Glow-Rasters als harte Bl\u00f6cke sichtbar "
            "wurden. Beim Deaktivieren war die Weichzeichnung wieder da.\n\n"
            "Eine CSS-Eigenheit: Verzerrung und Glow-Weichzeichnung sind "
            "dieselbe Eigenschaft, daher hat die Verzerrung die "
            "Weichzeichnung *ersetzt* statt sie zu erg\u00e4nzen. Jetzt "
            "werden beide gemeinsam angewendet.\n\n"
            "Betroffen war nur der Ersatz-Renderpfad. Wenn deine "
            "Grafikkarte den schnelleren Pfad unterst\u00fctzt, ist dir das "
            "nie begegnet.\n\n"
            "**Neuimport n\u00f6tig** — das Wallpaper selbst hat sich "
            "ge\u00e4ndert. In Lively das Wallpaper entfernen und die neue "
            "Zip importieren; in Wallpaper Engine neu abonnieren bzw. "
            "das Bundle neu importieren.\n"
        ),
    },
    "2.4.4-beta.14": {
        "title_en": "What's new in v2.4.4-beta.14",
        "title_de": "Was ist neu in v2.4.4-beta.14",
        "body_en": (
            "**Fixed: changing the glow grid size did nothing on one "
            "monitor.**\n\n"
            "With two monitors, changing *Glow Grid Base Size* or "
            "*Aspect Ratio* in SignalRGB only took effect on one of "
            "them. The other silently kept its old grid — and which one "
            "got stuck was down to chance, so the setting looked "
            "randomly broken.\n\n"
            "The plugin remembered \"something changed, rebuild the "
            "grid\" once for all monitors instead of once per monitor. "
            "Whichever screen redrew first used up that note, and the "
            "second never saw it. Now each monitor keeps its own.\n\n"
            "If a monitor's glow looks blocky, this is also worth "
            "checking in SignalRGB → Devices → Desktop Wallpaper:\n"
            "- **Aspect Ratio** should be *Auto* — a value left over "
            "from a previous monitor arrangement makes the glow squares "
            "stretched instead of square.\n"
            "- **Glow Grid Base Size** controls how fine the glow is. "
            "64 gives noticeably smaller squares than 36.\n\n"
            "The glow slider formerly called *Strength* is now "
            "**Spread**, because that is all it ever did: it scales "
            "the blur, not the brightness. Turning it down makes the "
            "glow grid\'s squares stop overlapping, so their edges "
            "become visible. Preset slot 1 stores 50 % and slot 4 "
            "stores 100 %, which is why those two slots looked so "
            "different. Nothing about how your saved slots render "
            "has changed — only the label and an added hint.\n\n"
            "**Fixed: the update check offered an older beta.**\n\n"
            "Version numbers were compared as text, so \"beta.9\" "
            "counted as newer than \"beta.10\" — nine is bigger than "
            "one, character by character. From beta.10 onwards the tray "
            "kept offering beta.9 and never saw anything newer.\n\n"
            "Note this fix can only work from the next update onwards: "
            "the version you are upgrading *from* still has the old "
            "comparison.\n\n"
            "**No re-import needed** — the wallpaper itself is unchanged "
            "since beta.12.\n"
        ),
        "body_de": (
            "**Behoben: Die Glow-Rastergröße zu ändern bewirkte auf "
            "einem Monitor nichts.**\n\n"
            "Mit zwei Monitoren wirkte eine Änderung an *Glow Grid Base "
            "Size* oder *Aspect Ratio* in SignalRGB nur auf einem von "
            "beiden. Der andere behielt still sein altes Raster — und "
            "welcher hängenblieb, war Zufall. Die Einstellung wirkte "
            "dadurch willkürlich kaputt.\n\n"
            "Das Plugin merkte sich „etwas hat sich geändert, Raster neu "
            "berechnen\" einmal für alle Monitore statt einmal pro "
            "Monitor. Welcher Bildschirm zuerst neu zeichnete, "
            "verbrauchte diese Notiz, der zweite sah sie nie. Jetzt hat "
            "jeder Monitor seine eigene.\n\n"
            "Falls der Glow auf einem Monitor klotzig aussieht, lohnt "
            "sich zusätzlich ein Blick in SignalRGB → Geräte → Desktop "
            "Wallpaper:\n"
            "- **Aspect Ratio** sollte auf *Auto* stehen — ein Wert aus "
            "einer früheren Monitoranordnung macht die Glow-Kästchen "
            "verzerrt statt quadratisch.\n"
            "- **Glow Grid Base Size** bestimmt, wie fein der Glow ist. "
            "64 ergibt spürbar kleinere Kästchen als 36.\n\n"
            "Der Glow-Regler, der bisher *Stärke* hieß, heißt jetzt "
            "**Ausbreitung** — denn mehr hat er nie getan: Er "
            "skaliert die Weichzeichnung, nicht die Helligkeit. "
            "Dreht man ihn herunter, überlappen sich die Kästchen "
            "des Glow-Rasters nicht mehr und ihre Kanten werden "
            "sichtbar. Voreinstellung Slot 1 speichert 50 %, Slot 4 "
            "dagegen 100 % — daher sahen diese beiden Slots so "
            "unterschiedlich aus. An der Darstellung gespeicherter "
            "Slots ändert sich nichts, nur die Beschriftung.\n\n"
            "**Behoben: Die Update-Prüfung bot eine ältere Beta an.**\n\n"
            "Versionsnummern wurden als Text verglichen, dadurch galt "
            "„beta.9\" als neuer als „beta.10\" — Zeichen für Zeichen "
            "ist die Neun größer als die Eins. Ab beta.10 bot der Tray "
            "immer wieder beta.9 an und sah nichts Neueres mehr.\n\n"
            "Dieser Fix kann erst ab dem nächsten Update greifen: Die "
            "Version, von der aus du aktualisierst, hat noch den alten "
            "Vergleich.\n\n"
            "**Kein Re-Import nötig** — das Wallpaper selbst ist seit "
            "beta.12 unverändert.\n"
        ),
    },
    "2.4.4-beta.12": {
        "title_en": "What's new in v2.4.4-beta.12",
        "title_de": "Was ist neu in v2.4.4-beta.12",
        "body_en": (
            "**Fixed: Liquid Distortion made the background dark and "
            "wrongly coloured until you moved the mouse.**\n\n"
            "Switching the effect on applied its distortion to the "
            "wallpaper before the distortion map existed. With nothing "
            "to bend the image by, the filter tore the colours apart "
            "instead — so the background looked dark and off, then "
            "visibly jumped the moment the first mouse movement filled "
            "the map in.\n\n"
            "Turning the effect off and on again appeared to fix it, "
            "because by then the map had content. That was a "
            "workaround, not a different setting.\n\n"
            "The water effect never had this problem — it prepares the "
            "map before the filter can touch the image, and keeps the "
            "strength at zero until then. Liquid Distortion now does "
            "the same.\n\n"
            "So: if the background looks darker to you after this "
            "update than it did before, that darker version is the "
            "correct one. What you saw earlier was the broken filter.\n\n"
            "**Requires re-importing the wallpaper bundle.**\n"
        ),
        "body_de": (
            "**Behoben: Die flüssige Verzerrung machte den Hintergrund "
            "dunkel und farblich falsch, bis man die Maus bewegte.**\n\n"
            "Beim Einschalten wurde die Verzerrung auf das Wallpaper "
            "angewendet, bevor die Verzerrungskarte überhaupt "
            "existierte. Ohne etwas, womit sich das Bild biegen ließe, "
            "zerriss der Filter stattdessen die Farben — der Hintergrund "
            "wirkte dunkel und daneben und sprang sichtbar um, sobald "
            "die erste Mausbewegung die Karte füllte.\n\n"
            "Den Effekt aus- und wieder einzuschalten schien zu helfen, "
            "weil die Karte dann bereits Inhalt hatte. Das war ein "
            "Umweg, keine andere Einstellung.\n\n"
            "Der Wassereffekt hatte das Problem nie — er bereitet die "
            "Karte vor, bevor der Filter das Bild anfassen kann, und "
            "hält die Stärke bis dahin auf null. Die flüssige "
            "Verzerrung macht das jetzt genauso.\n\n"
            "Das heißt: Wenn dir der Hintergrund nach diesem Update "
            "dunkler vorkommt als vorher — diese dunklere Fassung ist "
            "die richtige. Was du vorher gesehen hast, war der kaputte "
            "Filter.\n\n"
            "**Erfordert einen Re-Import des Wallpaper-Bundles.**\n"
        ),
    },
    "2.4.4-beta.11": {
        "title_en": "What's new in v2.4.4-beta.11",
        "title_de": "Was ist neu in v2.4.4-beta.11",
        "body_en": (
            "**The wallpaper now tells you why it's black.**\n\n"
            "Getting this running takes six steps, and two of them are "
            "easy to miss: dragging the *Desktop Wallpaper* device onto "
            "the SignalRGB canvas, and assigning the wallpaper to a "
            "monitor. Miss the first and everything looks fine — the "
            "bridge is running, the Configurator says \"connected\" — "
            "while the screen stays black and nothing anywhere says "
            "why.\n\n"
            "- The Configurator now shows a banner naming the next step "
            "whenever the chain is broken, with a button to jump "
            "straight there. It stays out of the way when everything "
            "works.\n"
            "- The wallpaper's own \"bridge offline\" card learned a "
            "second message for the case above: connected, but nothing "
            "is being sent.\n"
            "- Both are now shown in your language. The card was the "
            "last English-only corner of the app — and it appears "
            "exactly when you least want to be puzzling over "
            "English.\n\n"
            "**Also: help wanted with the memory question.**\n"
            "Memory climbs over a long session and does not fully come "
            "back. There is a prime suspect — a fallback drawing path "
            "that leaves an image in the browser's cache on every frame "
            "— but no proof, and two earlier fix attempts made things "
            "worse because they were built on a theory instead of a "
            "measurement.\n\n"
            "So this build only counts. It records once a minute which "
            "drawing path is actually running, into the log you already "
            "have. Use the wallpaper normally for a day; the log will "
            "settle the question either way.\n\n"
            "**Requires re-importing the wallpaper bundle.**\n"
        ),
        "body_de": (
            "**Das Wallpaper sagt jetzt, warum es schwarz ist.**\n\n"
            "Bis alles läuft, sind sechs Schritte nötig, und zwei davon "
            "übersieht man leicht: das Gerät *Desktop Wallpaper* auf die "
            "SignalRGB-Fläche zu ziehen und das Wallpaper einem Monitor "
            "zuzuweisen. Fehlt der erste, sieht alles in Ordnung aus — "
            "die Bridge läuft, der Configurator meldet „verbunden“ — "
            "während der Bildschirm schwarz bleibt und nirgends steht, "
            "warum.\n\n"
            "- Der Configurator zeigt jetzt einen Hinweis mit dem "
            "nächsten Schritt, sobald etwas in der Kette fehlt, samt "
            "Knopf, der direkt dorthin führt. Läuft alles, hält er sich "
            "raus.\n"
            "- Die „Bridge offline“-Karte auf dem Wallpaper hat einen "
            "zweiten Text für genau den Fall oben bekommen: verbunden, "
            "aber es wird nichts gesendet.\n"
            "- Beides erscheint jetzt auf Deutsch. Die Karte war die "
            "letzte rein englische Ecke der App — und sie taucht genau "
            "dann auf, wenn man am wenigsten Lust auf Englisch hat.\n\n"
            "**Außerdem: Mithilfe bei der Speicherfrage.**\n"
            "Der Speicherverbrauch steigt über eine lange Sitzung und "
            "geht nicht vollständig zurück. Es gibt einen "
            "Hauptverdächtigen — ein Ersatz-Zeichenweg, der pro Bild "
            "eine Grafik im Browser-Cache zurücklässt — aber keinen "
            "Beweis. Zwei frühere Reparaturversuche haben es "
            "verschlimmert, weil sie auf einer Theorie statt einer "
            "Messung beruhten.\n\n"
            "Dieser Build zählt deshalb nur. Er schreibt einmal pro "
            "Minute mit, welcher Zeichenweg tatsächlich läuft — in das "
            "Log, das du ohnehin hast. Nutze das Wallpaper einen Tag "
            "normal; das Log klärt die Frage in beide Richtungen.\n\n"
            "**Erfordert einen Re-Import des Wallpaper-Bundles.**\n"
        ),
    },
    "2.4.4-beta.10": {
        "title_en": "What's new in v2.4.4-beta.10",
        "title_de": "Was ist neu in v2.4.4-beta.10",
        "body_en": (
            "**Fixed: water and mouse distortion could die permanently "
            "on one screen.**\n\n"
            "Both effects run on the graphics card, and the browser "
            "sometimes drops that connection — a driver update, waking "
            "from sleep, or the host suspending the wallpaper. Recovery "
            "was broken: the background image was never handed back to "
            "the graphics card afterwards, and the wallpaper still "
            "believed everything was fine, so it never fell back to the "
            "slower-but-working path either.\n\n"
            "The result was exactly what one user described: water and "
            "mouse distortion completely dead on one screen while the "
            "glow and widgets carried on. Only reloading the wallpaper "
            "brought them back.\n\n"
            "Now the image is re-uploaded when the connection returns, "
            "and while it is gone the effects switch to the fallback "
            "path instead of silently doing nothing.\n\n"
            "**Still open:** memory climbing over a long session. "
            "Measured and confirmed — roughly 80 MB stays behind after "
            "each burst of clicking and mouse movement — but the cause "
            "is not yet found. This release may help if the graphics "
            "connection was dropping repeatedly; that is a hypothesis, "
            "not a fix.\n\n"
            "**Requires re-importing the wallpaper bundle.**\n"
        ),
        "body_de": (
            "**Behoben: Wasserwelle und Mausverzerrung konnten auf "
            "einem Bildschirm dauerhaft ausfallen.**\n\n"
            "Beide Effekte laufen über die Grafikkarte, und der Browser "
            "verliert diese Verbindung gelegentlich — bei einem "
            "Treiber-Update, beim Aufwachen aus dem Ruhezustand oder "
            "wenn der Host das Wallpaper aussetzt. Die "
            "Wiederherstellung war kaputt: Das Hintergrundbild wurde "
            "danach nie wieder an die Grafikkarte übergeben, und das "
            "Wallpaper hielt trotzdem alles für in Ordnung — also fiel "
            "es auch nicht auf den langsameren, aber funktionierenden "
            "Weg zurück.\n\n"
            "Das Ergebnis war genau das gemeldete Bild: Wasserwelle und "
            "Mausverzerrung auf einem Bildschirm komplett tot, während "
            "Glow und Widgets weiterliefen. Nur ein Neuladen des "
            "Wallpapers half.\n\n"
            "Jetzt wird das Bild neu übergeben, sobald die Verbindung "
            "zurück ist — und solange sie fehlt, schalten die Effekte "
            "auf den Ersatzweg um, statt stillschweigend nichts zu "
            "tun.\n\n"
            "**Weiterhin offen:** Der Speicherverbrauch steigt über "
            "eine lange Sitzung. Gemessen und bestätigt — nach jeder "
            "Phase mit Klicken und Mausbewegung bleiben rund 80 MB "
            "zurück — die Ursache ist aber noch nicht gefunden. Diese "
            "Version könnte helfen, falls die Grafikverbindung wiederholt "
            "abriss; das ist eine Vermutung, keine Lösung.\n\n"
            "**Erfordert einen Re-Import des Wallpaper-Bundles.**\n"
        ),
    },
    "2.4.4-beta.9": {
        "title_en": "What's new in v2.4.4-beta.9",
        "title_de": "Was ist neu in v2.4.4-beta.9",
        "body_en": (
            "**Fixed: applying a second image to a spanned screen "
            "erased the first.**\n\n"
            "On a spanned setup you can send a library image to just "
            "the left or right half. Applying to one half and then the "
            "other wiped whichever you did first — on both Lively and "
            "Wallpaper Engine.\n\n"
            "The second apply builds a new image by copying the half "
            "you already set and drawing the new picture beside it. It "
            "was reading the existing background from a cache that "
            "refreshes every five seconds, so if you clicked the second "
            "half sooner than that, it copied the state from before the "
            "first one — and your first image went with it. Waiting a "
            "few seconds between clicks happened to work, which is "
            "why this was easy to miss.\n\n"
            "It now reads the live value, so the halves survive no "
            "matter how quickly you work.\n\n"
            "**No re-import needed** for this one — the wallpaper "
            "itself is unchanged since beta.8.\n"
        ),
        "body_de": (
            "**Behoben: Ein zweites Bild auf einem gespannten "
            "Bildschirm löschte das erste.**\n\n"
            "Auf einem gespannten Setup kann man ein Bild aus der "
            "Bibliothek nur auf die linke oder rechte Hälfte legen. "
            "Erst die eine, dann die andere Hälfte zu belegen löschte "
            "jeweils die zuerst gesetzte — unter Lively wie unter "
            "Wallpaper Engine.\n\n"
            "Der zweite Vorgang baut ein neues Bild, indem er die "
            "bereits gesetzte Hälfte übernimmt und das neue Bild "
            "daneben zeichnet. Dabei las er den vorhandenen Hintergrund "
            "aus einem Zwischenspeicher, der nur alle fünf Sekunden "
            "aktualisiert wird — wer schneller klickte, übernahm den "
            "Stand von vor der ersten Hälfte, und das erste Bild war "
            "weg. Ein paar Sekunden Pause zwischen den Klicks "
            "funktionierte zufällig, weshalb das leicht zu übersehen "
            "war.\n\n"
            "Jetzt wird der Live-Wert gelesen; beide Hälften bleiben "
            "erhalten, egal wie schnell man arbeitet.\n\n"
            "**Kein Re-Import nötig** — das Wallpaper selbst ist seit "
            "beta.8 unverändert.\n"
        ),
    },
    "2.4.4-beta.8": {
        "title_en": "What's new in v2.4.4-beta.8",
        "title_de": "Was ist neu in v2.4.4-beta.8",
        "body_en": (
            "**Hotfix — beta.7 was broken.**\n\n"
            "If you installed beta.7 you got a black wallpaper with a "
            "\"bridge offline\" card, whatever the bridge was actually "
            "doing. A variable declaration was deleted along with the "
            "code block that had grown around it, and the page stopped "
            "starting up at all. Sorry about that.\n\n"
            "Everything beta.7 was meant to deliver is intact — the "
            "Fireflies and Sparks speed-up, the quality-aware glow "
            "sizes, the \"apply to all screens\" fix. This is beta.7 "
            "with the page working.\n\n"
            "The test suite now runs the wallpaper's start-up code "
            "instead of only checking that it parses. That was the gap "
            "that let this through: the file was perfectly valid "
            "JavaScript, it just died on the first line that mattered.\n\n"
            "**Requires re-importing the wallpaper bundle** — as with "
            "the earlier betas.\n"
        ),
        "body_de": (
            "**Hotfix — beta.7 war kaputt.**\n\n"
            "Wer beta.7 installiert hat, bekam ein schwarzes Wallpaper "
            "mit „Bridge offline“-Karte — unabhängig davon, was die "
            "Bridge tatsächlich tat. Eine Variablen-Deklaration wurde "
            "zusammen mit dem Codeblock gelöscht, der um sie herum "
            "gewachsen war, und die Seite startete gar nicht mehr. "
            "Sorry dafür.\n\n"
            "Alles, was beta.7 bringen sollte, ist intakt — die "
            "Beschleunigung von Glühwürmchen und Funken, die "
            "qualitätsabhängigen Leuchtgrößen, der Fix für „Auf alle "
            "Bildschirme anwenden“. Das hier ist beta.7 mit "
            "funktionierender Seite.\n\n"
            "Die Testsuite führt den Startcode des Wallpapers jetzt "
            "wirklich aus, statt nur zu prüfen, ob er sich parsen "
            "lässt. Genau diese Lücke hat den Fehler durchgelassen: "
            "Die Datei war einwandfreies JavaScript — sie starb nur "
            "an der ersten Zeile, auf die es ankam.\n\n"
            "**Erfordert einen Re-Import des Wallpaper-Bundles** — wie "
            "bei den vorherigen Betas.\n"
        ),
    },
    "2.4.4-beta.7": {
        "title_en": "What's new in v2.4.4-beta.7",
        "title_de": "Was ist neu in v2.4.4-beta.7",
        "body_en": (
            "This one should be noticeably lighter on the graphics "
            "card, and it starts with an admission: a change in "
            "beta.5 made things worse, not better.\n\n"
            "**Fireflies and Sparks are back to how they used to draw**\n"
            "- beta.5 switched them to a pre-drawn glow image, on the "
            "theory that rebuilding the glow for each particle every "
            "frame was wasteful. Measured properly, the pre-drawn "
            "version was about four times slower — the browser has a "
            "much faster route for the original approach.\n"
            "- On a 5120×1440 desktop, Fireflies alone was using two "
            "thirds of the wallpaper's graphics load. That should now "
            "be roughly a quarter of what it was.\n\n"
            "**The quality setting reaches the big soft effects**\n"
            "- Aurora, Plasma and similar presets draw glows far "
            "larger than the particle behind them. Those now shrink "
            "with the effect-quality setting: about 18 % less work on "
            "Balanced, 32 % on Performance. Quality is untouched.\n\n"
            "**Removed: the \"cheaper blur\" option from beta.6**\n"
            "- It made no measurable difference and has been taken out "
            "again. If you selected it, you will be back on plain "
            "Canvas automatically. The glow grid turned out not to "
            "cost anything worth optimising in the first place.\n\n"
            "**Fixed:** \"Apply to all screens\" in the Configurator "
            "never worked — the request failed silently. It does now.\n\n"
            "**Requires re-importing the wallpaper bundle** — as with "
            "the earlier betas.\n"
        ),
        "body_de": (
            "Diese Version sollte die Grafikkarte spürbar entlasten — "
            "und sie beginnt mit einem Eingeständnis: Eine Änderung in "
            "beta.5 hat es verschlechtert statt verbessert.\n\n"
            "**Glühwürmchen und Funken zeichnen wieder wie früher**\n"
            "- beta.5 stellte sie auf ein vorgezeichnetes Leuchtbild "
            "um, in der Annahme, das Neuaufbauen pro Partikel und Bild "
            "sei verschwenderisch. Richtig gemessen war die "
            "vorgezeichnete Variante rund viermal langsamer — der "
            "Browser hat für den ursprünglichen Weg eine deutlich "
            "schnellere Route.\n"
            "- Auf einem 5120×1440-Desktop verbrauchten allein die "
            "Glühwürmchen zwei Drittel der Grafiklast des Wallpapers. "
            "Das sollte jetzt etwa ein Viertel davon sein.\n\n"
            "**Die Qualitätsstufe erreicht die großen weichen Effekte**\n"
            "- Aurora, Plasma und ähnliche Presets zeichnen ein "
            "Leuchten, das weit größer ist als das Partikel dahinter. "
            "Das schrumpft jetzt mit der Qualitätsstufe: rund 18 % "
            "weniger Aufwand bei Ausgewogen, 32 % bei Performance. "
            "Qualität bleibt unverändert.\n\n"
            "**Entfernt: die Option „günstigerer Blur“ aus beta.6**\n"
            "- Sie brachte keinen messbaren Unterschied und ist wieder "
            "raus. Falls du sie ausgewählt hattest, landest du "
            "automatisch wieder bei normalem Canvas. Das Glow-Raster "
            "kostet ohnehin nichts, was sich zu optimieren lohnt.\n\n"
            "**Behoben:** „Auf alle Bildschirme anwenden“ im "
            "Configurator hat nie funktioniert — die Anfrage schlug "
            "stillschweigend fehl. Jetzt geht es.\n\n"
            "**Erfordert einen Re-Import des Wallpaper-Bundles** — wie "
            "bei den vorherigen Betas.\n"
        ),
    },
    "2.4.4-beta.6": {
        "title_en": "What's new in v2.4.4-beta.6",
        "title_de": "Was ist neu in v2.4.4-beta.6",
        "body_en": (
            "One new option to try, aimed at wide and spanned "
            "desktops.\n\n"
            "**Glow → Grid renderer → \"Canvas — cheaper blur\"**\n"
            "- The glow grid is a small image that gets stretched "
            "across your whole desktop and then blurred. On a wide or "
            "spanned setup that blur runs over several million pixels "
            "every frame, and it is roughly a third of what the "
            "wallpaper costs your graphics card.\n"
            "- The new option draws the same picture a different way: "
            "a larger intermediate image with a proportionally smaller "
            "blur. It should look identical — if you can see any "
            "difference between it and plain Canvas, that's a bug "
            "worth reporting.\n"
            "- Measured at about 23 % less blur work in isolation. "
            "Whether that shows up on your machine is exactly what "
            "this option is for, so it is a choice rather than the new "
            "default.\n\n"
            "**Requires re-importing the wallpaper bundle** — as with "
            "the earlier betas.\n"
        ),
        "body_de": (
            "Eine neue Option zum Ausprobieren, gedacht für breite und "
            "gespannte Desktops.\n\n"
            "**Glow → Grid-Renderer → „Canvas — günstigerer Blur“**\n"
            "- Das Glow-Raster ist ein kleines Bild, das über den "
            "ganzen Desktop gezogen und dann weichgezeichnet wird. Auf "
            "einem breiten oder gespannten Setup läuft dieser Blur in "
            "jedem Bild über mehrere Millionen Pixel und macht etwa "
            "ein Drittel dessen aus, was das Wallpaper deine Grafikkarte "
            "kostet.\n"
            "- Die neue Option zeichnet dasselbe Bild auf anderem Weg: "
            "ein größeres Zwischenbild mit entsprechend kleinerem Blur. "
            "Es sollte identisch aussehen — falls du einen Unterschied "
            "zum normalen Canvas siehst, ist das ein meldenswerter "
            "Fehler.\n"
            "- Isoliert gemessen rund 23 % weniger Blur-Aufwand. Ob "
            "sich das auf deiner Maschine zeigt, ist genau die Frage, "
            "für die es diese Option gibt — deshalb eine Wahl und nicht "
            "der neue Standard.\n\n"
            "**Erfordert einen Re-Import des Wallpaper-Bundles** — wie "
            "bei den vorherigen Betas.\n"
        ),
    },
    "2.4.4-beta.5": {
        "title_en": "What's new in v2.4.4-beta.5",
        "title_de": "Was ist neu in v2.4.4-beta.5",
        "body_en": (
            "More efficiency work, and again nothing should look "
            "different. If Fireflies, Sparks or Wormhole changed "
            "appearance for you, that's a bug worth reporting.\n\n"
            "**Fireflies and Sparks got much cheaper to draw**\n"
            "- Both rebuilt every particle's glow from scratch on every "
            "single frame — around ten thousand throwaway gradients a "
            "second on a 1440p desktop. The glow is now drawn once and "
            "reused, which removes that work entirely.\n"
            "- Sparks also stopped painting a square around its round "
            "glow, the same fix Aurora and Plasma got in the last beta.\n\n"
            "**The quality setting now reaches the effect that needed "
            "it most**\n"
            "- Wormhole's glow is the single most expensive thing the "
            "wallpaper draws — measured at roughly a quarter of the "
            "frame budget on a 1440p desktop. It ignored the effect-"
            "quality setting completely, so choosing Performance did "
            "nothing for it.\n"
            "- Balanced and Performance now trade some glow radius for "
            "frame time (about 20 % and 39 % less work). Quality is "
            "unchanged — if you liked how it looked, leave it there.\n\n"
            "**Under the hood**\n"
            "- The bridge's request handling was split into separate "
            "routes. No behaviour change; it is simply no longer one "
            "1,600-line function.\n"
            "- Groundwork for a future Linux version: the bridge now "
            "starts without a Windows-only GUI stack.\n\n"
            "**Requires re-importing the wallpaper bundle** — as with "
            "the earlier betas.\n"
        ),
        "body_de": (
            "Weitere Effizienzarbeit, und auch hier sollte sich optisch "
            "nichts ändern. Falls Glühwürmchen, Funken oder Wurmloch bei "
            "dir anders aussehen, ist das ein meldenswerter Fehler.\n\n"
            "**Glühwürmchen und Funken sind deutlich günstiger geworden**\n"
            "- Beide haben das Leuchten jedes Partikels in jedem "
            "einzelnen Bild neu aufgebaut — rund zehntausend "
            "Wegwerf-Verläufe pro Sekunde auf einem 1440p-Desktop. Das "
            "Leuchten wird jetzt einmal gezeichnet und wiederverwendet.\n"
            "- Funken malt außerdem kein Quadrat mehr um sein rundes "
            "Leuchten — derselbe Fix, den Aurora und Plasma in der "
            "letzten Beta bekommen haben.\n\n"
            "**Die Qualitätsstufe erreicht jetzt den Effekt, der sie am "
            "nötigsten hatte**\n"
            "- Das Leuchten von Wurmloch ist das mit Abstand teuerste, "
            "was das Wallpaper zeichnet — gemessen etwa ein Viertel des "
            "Bildbudgets auf 1440p. Die Qualitätsstufe wurde dabei "
            "komplett ignoriert, „Performance“ brachte also nichts.\n"
            "- Ausgewogen und Performance tauschen jetzt etwas "
            "Leuchtradius gegen Bildzeit (rund 20 % bzw. 39 % weniger "
            "Aufwand). Qualität bleibt unverändert.\n\n"
            "**Unter der Haube**\n"
            "- Die Anfrageverarbeitung der Bridge wurde in einzelne "
            "Routen aufgeteilt. Kein Verhaltensunterschied — es ist "
            "einfach keine 1.600-Zeilen-Funktion mehr.\n"
            "- Vorarbeit für eine künftige Linux-Version: Die Bridge "
            "startet jetzt auch ohne den Windows-GUI-Unterbau.\n\n"
            "**Erfordert einen Re-Import des Wallpaper-Bundles** — wie "
            "bei den vorherigen Betas.\n"
        ),
    },
    "2.4.4-beta.4": {
        "title_en": "What's new in v2.4.4-beta.4",
        "title_de": "Was ist neu in v2.4.4-beta.4",
        "body_en": (
            "Efficiency work on the soft-glow effects. Nothing should "
            "look different — if Aurora, Plasma or Fireflies changed "
            "appearance for you, that's a bug worth reporting.\n\n"
            "**Less GPU work for the same picture**\n"
            "- Aurora, Plasma and Fireflies each painted a square around "
            "a round glow. The corners were fully transparent but the "
            "graphics card still had to blend them, and they made up a "
            "fifth of everything these effects drew. They now paint the "
            "circle itself.\n"
            "- This matters most on wide desktops, where the previous "
            "beta made these blobs considerably larger: Plasma alone was "
            "filling more than a full screen's worth of pixels every "
            "frame on an ultrawide.\n\n"
            "**Effect previews can no longer flatter the real thing**\n"
            "- The small animated previews in the effect picker are a "
            "separate piece of code from the effects themselves, and the "
            "two had drifted apart. Aurora's preview was nearly three "
            "times as strong as the effect it advertised — which is part "
            "of why the effect being invisible went unnoticed for so "
            "long.\n"
            "- A check now flags it when a preview promises noticeably "
            "more than the effect delivers.\n\n"
            "**Requires re-importing the wallpaper bundle** — as with "
            "the earlier betas.\n"
        ),
        "body_de": (
            "Effizienzarbeit an den weichen Leuchteffekten. Es sollte "
            "sich nichts sichtbar ändern — falls Aurora, Plasma oder "
            "Glühwürmchen bei dir anders aussehen, ist das ein Fehler "
            "und einen Hinweis wert.\n\n"
            "**Weniger GPU-Arbeit für dasselbe Bild**\n"
            "- Aurora, Plasma und Glühwürmchen zeichneten jeweils ein "
            "Quadrat um einen runden Lichtschein. Die Ecken waren zwar "
            "vollständig durchsichtig, mussten von der Grafikkarte aber "
            "trotzdem verrechnet werden — und machten ein Fünftel von "
            "allem aus, was diese Effekte zeichnen. Jetzt wird der Kreis "
            "selbst gezeichnet.\n"
            "- Das zählt vor allem auf breiten Desktops, wo die "
            "vorherige Beta diese Flecken deutlich vergrößert hat: "
            "Allein Plasma füllte auf einem Ultrawide pro Bild mehr als "
            "eine komplette Bildschirmfläche.\n\n"
            "**Effekt-Vorschauen können nicht mehr schöner sein als das "
            "Original**\n"
            "- Die kleinen animierten Vorschauen im Effekt-Picker sind "
            "eigener Code, getrennt von den Effekten selbst — und beide "
            "waren auseinandergelaufen. Auroras Vorschau war fast "
            "dreimal so kräftig wie der beworbene Effekt. Auch deshalb "
            "blieb lange unbemerkt, dass der Effekt unsichtbar war.\n"
            "- Eine Prüfung meldet jetzt, wenn eine Vorschau spürbar "
            "mehr verspricht, als der Effekt liefert.\n\n"
            "**Erfordert einen Re-Import des Wallpaper-Bundles** — wie "
            "bei den vorherigen Betas.\n"
        ),
    },
    "2.4.4-beta.3": {
        "title_en": "What's new in v2.4.4-beta.3",
        "title_de": "Was ist neu in v2.4.4-beta.3",
        "body_en": (
            "**Aurora and Plasma are actually visible now**\n\n"
            "Both looked no different from having the effect switched "
            "off, on either host. They were drawing the whole time — just "
            "far too faintly to notice.\n\n"
            "Two things were wrong, and both only showed up on larger "
            "screens:\n"
            "- The soft colour blobs had a fixed size in pixels, chosen "
            "for a 1920×1080 desktop. On a wider screen each one covers "
            "a much smaller share of it, and the number of blobs never "
            "grew either. Both now scale with your screen.\n"
            "- They were also drawn far too transparently. Measured "
            "against a real wallpaper rather than a black screen, the "
            "colour barely shifted at all. Every other ambient effect "
            "uses roughly twice to six times as much. Aurora and Plasma "
            "are now about twice as strong and keep their shape further "
            "out from the centre.\n\n"
            "Nothing changes on a 1920×1080 screen — the scaling only "
            "ever adds, so the original look is preserved there.\n\n"
            "**Requires re-importing the wallpaper bundle** — as with "
            "the earlier betas. Configurator → System → *Re-import "
            "wallpaper bundles…*, then re-apply the wallpaper in "
            "Wallpaper Engine.\n"
        ),
        "body_de": (
            "**Aurora und Plasma sind jetzt wirklich sichtbar**\n\n"
            "Beide sahen auf beiden Hosts aus, als wäre der Effekt "
            "ausgeschaltet. Gezeichnet wurde die ganze Zeit — nur viel "
            "zu schwach, um es zu bemerken.\n\n"
            "Zwei Dinge waren falsch, und beide fielen erst auf großen "
            "Bildschirmen auf:\n"
            "- Die weichen Farbflecken hatten eine feste Größe in Pixeln, "
            "ausgelegt für einen 1920×1080-Desktop. Auf einem breiteren "
            "Bildschirm deckt jeder davon einen viel kleineren Teil ab, "
            "und die Anzahl wuchs ebenfalls nicht mit. Beides skaliert "
            "jetzt mit deinem Bildschirm.\n"
            "- Außerdem wurden sie viel zu durchsichtig gezeichnet. "
            "Gegen ein echtes Wallpaper gemessen statt gegen einen "
            "schwarzen Bildschirm verschob sich die Farbe kaum. Alle "
            "anderen Ambient-Effekte nutzen etwa das Doppelte bis "
            "Sechsfache. Aurora und Plasma sind jetzt rund doppelt so "
            "kräftig und behalten ihre Form weiter nach außen.\n\n"
            "Auf einem 1920×1080-Bildschirm ändert sich nichts — die "
            "Skalierung legt nur zu, das ursprüngliche Aussehen bleibt "
            "dort erhalten.\n\n"
            "**Erfordert einen Re-Import des Wallpaper-Bundles** — wie "
            "bei den vorherigen Betas. Configurator → System → "
            "*Wallpaper-Bundles neu importieren…*, danach das Wallpaper "
            "in Wallpaper Engine erneut zuweisen.\n"
        ),
    },
    "2.4.4-beta.2": {
        "title_en": "What's new in v2.4.4-beta.2",
        "title_de": "Was ist neu in v2.4.4-beta.2",
        "body_en": (
            "Two fixes on top of beta.1, both reported from real use.\n\n"
            "**The Waves effect stopped partway across the desktop**\n"
            "- The lines were drawn across only half or three quarters of "
            "the screen and cut off mid-monitor, depending on the Effect "
            "quality setting. On a wide multi-monitor desktop this was "
            "hard to miss.\n"
            "- Waves was the only effect that worked out its own drawing "
            "width, and it did so from the wrong number. It now reads the "
            "value actually in use, so it spans the full desktop in every "
            "quality bucket.\n\n"
            "**Widgets could sit at “loading” forever**\n"
            "- A widget that fetches data — weather most visibly — only "
            "did so from the shared once-a-second update. Wallpaper "
            "Engine suspends that update while a wallpaper is paused, so "
            "a widget created in that window never loaded and stayed "
            "blank until it was re-saved.\n"
            "- New widgets now get their first update immediately, "
            "through a path the host does not suspend.\n\n"
            "**Requires re-importing the wallpaper bundle** — as with "
            "beta.1. Configurator → System → *Re-import wallpaper "
            "bundles…*, then re-apply the wallpaper in Wallpaper "
            "Engine.\n"
        ),
        "body_de": (
            "Zwei Korrekturen auf beta.1 auf, beide aus dem echten "
            "Einsatz gemeldet.\n\n"
            "**Der Wellen-Effekt hörte mitten auf dem Desktop auf**\n"
            "- Die Linien wurden je nach Effekt-Qualität nur über die "
            "Hälfte oder drei Viertel des Bildschirms gezeichnet und "
            "brachen mitten auf einem Monitor ab. Auf einem breiten "
            "Multi-Monitor-Desktop fiel das deutlich auf.\n"
            "- Wellen war der einzige Effekt, der seine Zeichenbreite "
            "selbst ermittelte — und dabei den falschen Wert nahm. Er "
            "liest jetzt den tatsächlich verwendeten Wert und läuft in "
            "jeder Qualitätsstufe über den gesamten Desktop.\n\n"
            "**Widgets konnten dauerhaft auf „loading\" stehen bleiben**\n"
            "- Ein Widget, das Daten lädt — am sichtbarsten das Wetter — "
            "tat das ausschließlich über die gemeinsame Sekunden-"
            "Aktualisierung. Wallpaper Engine hält diese an, solange ein "
            "Wallpaper pausiert ist; ein in diesem Moment erzeugtes "
            "Widget lud daher nie und blieb leer, bis man es erneut "
            "gespeichert hat.\n"
            "- Neue Widgets holen ihre Daten jetzt sofort, über einen "
            "Weg, den der Host nicht anhält.\n\n"
            "**Erfordert einen Re-Import des Wallpaper-Bundles** — wie "
            "schon bei beta.1. Configurator → System → *Wallpaper-"
            "Bundles neu importieren…*, danach das Wallpaper in "
            "Wallpaper Engine erneut zuweisen.\n"
        ),
    },
    "2.4.4-beta.1": {
        "title_en": "What's new in v2.4.4-beta.1",
        "title_de": "Was ist neu in v2.4.4-beta.1",
        "body_en": (
            "**Fixed: tinted effects rendered as flat, solid colour.**\n\n"
            "Hover-Glow appeared as a hard blue disc instead of a soft "
            "glow, and it was not alone — every effect that takes its "
            "colour from the glow feed was affected the same way. The "
            "helper that fades a colour to transparent only understood "
            "one of the two colour formats in use, and silently returned "
            "the other unchanged. Every step of a gradient then came out "
            "the same fully-opaque colour.\n\n"
            "It showed up whenever the bridge had not yet sent a colour: "
            "at startup, after a restart, or with the bridge not running. "
            "Under Lively the connection is usually up before you first "
            "hover, which is why it looked like a Wallpaper Engine "
            "problem and why Hover-Glow carried a “Lively only” badge. "
            "That badge is gone — the effect works on both hosts.\n\n"
            "**Water-Ripple and Liquid Distortion now work in Wallpaper "
            "Engine.**\n"
            "- Both built their distortion from an image that WE's "
            "bundled browser silently refuses to load. Nothing arrived, "
            "so instead of a travelling wave you got a one-off shift on "
            "click — exactly what users described.\n"
            "- Earlier releases blamed a colour-space mismatch and "
            "shipped a correction for it in v2.3.0, which was removed "
            "again in v2.4.0 because it made no difference. It couldn't "
            "have: the image never arrived, so its colours were "
            "irrelevant.\n"
            "- Both effects now draw on the graphics card instead. Same "
            "look, and noticeably lighter on the CPU — the old path "
            "re-encoded a PNG about thirty times a second.\n"
            "- Still marked “Lively only” in the picker while this beta "
            "gets tested on more setups. Lively is unaffected either "
            "way; where the graphics path isn't available the previous "
            "rendering is used automatically.\n"
            "- Video backgrounds keep the old behaviour: these two "
            "effects stay off.\n\n"
            "**Pausing behaves properly now**\n"
            "- Pausing from Wallpaper Engine's own tray menu left the "
            "glow running and showed no PAUSED marker. WE pauses a "
            "wallpaper in a way that also silenced the check meant to "
            "notice it; the glow kept going because it arrives over a "
            "different channel. Both are handled.\n"
            "- In Lively, the pause used to hang on for a second or two "
            "after resuming, and the PAUSED marker appeared when you "
            "*un*-paused rather than when you paused. Fixed.\n"
            "- While a game is in the foreground the wallpaper now costs "
            "far less: the Desktop Window Manager was still being woken "
            "several times a second even though everything was paused "
            "(measured ~2 % CPU, now ~0.3 %).\n\n"
            "**Requires re-importing the wallpaper bundle** — the change "
            "is in the wallpaper page. Configurator → System → "
            "*Re-import wallpaper bundles…*, then re-apply the wallpaper "
            "in Wallpaper Engine. Steam Workshop subscribers get it "
            "automatically once the item is updated.\n"
        ),
        "body_de": (
            "**Behoben: getönte Effekte wurden als flache Farbfläche "
            "gezeichnet.**\n\n"
            "Hover-Glow erschien als harte blaue Scheibe statt als "
            "weiches Leuchten — und war damit nicht allein: Jeder "
            "Effekt, der seine Farbe aus dem Glow-Feed bezieht, war "
            "genauso betroffen. Die Hilfsfunktion, die eine Farbe nach "
            "transparent ausblendet, verstand nur eines der beiden "
            "verwendeten Farbformate und gab das andere unverändert "
            "zurück. Jede Stufe eines Verlaufs kam dadurch als dieselbe "
            "voll deckende Farbe heraus.\n\n"
            "Sichtbar wurde das immer dann, wenn die Bridge noch keine "
            "Farbe geliefert hatte: beim Start, nach einem Neustart oder "
            "wenn die Bridge nicht lief. Unter Lively steht die "
            "Verbindung meist schon, bevor man das erste Mal über den "
            "Desktop fährt — deshalb sah es nach einem Wallpaper-Engine-"
            "Problem aus, und deshalb trug Hover-Glow ein „Nur Lively\"-"
            "Badge. Das ist weg, der Effekt funktioniert auf beiden "
            "Hosts.\n\n"
            "**Wasserwelle und Flüssige Verzerrung funktionieren jetzt "
            "in Wallpaper Engine.**\n"
            "- Beide bauten ihre Verzerrung aus einem Bild, das der "
            "mitgelieferte Browser von Wallpaper Engine stillschweigend "
            "nicht lädt. Es kam nichts an, deshalb gab es statt einer "
            "laufenden Welle nur einen einmaligen Versatz beim Klick — "
            "genau das, was Nutzer beschrieben haben.\n"
            "- Frühere Releases hatten einen Farbraum-Fehler vermutet "
            "und in v2.3.0 eine Korrektur dafür ausgeliefert, die in "
            "v2.4.0 wieder entfernt wurde, weil sie nichts änderte. Sie "
            "konnte auch nichts ändern: Wenn das Bild nie ankommt, sind "
            "seine Farben egal.\n"
            "- Beide Effekte zeichnen jetzt über die Grafikkarte. "
            "Gleiches Aussehen, spürbar weniger CPU-Last — der alte Weg "
            "kodierte rund dreißig Mal pro Sekunde ein PNG neu.\n"
            "- Im Picker bleibt vorerst das „Nur Lively\"-Badge stehen, "
            "solange diese Beta auf mehr Systemen getestet wird. Lively "
            "ist davon unberührt; wo der Grafikpfad nicht verfügbar ist, "
            "wird automatisch die bisherige Darstellung genutzt.\n"
            "- Bei Video-Hintergründen bleibt es beim alten Verhalten: "
            "Diese beiden Effekte bleiben dort aus.\n\n"
            "**Pausieren funktioniert jetzt sauber**\n"
            "- Über das Tray-Menü von Wallpaper Engine zu pausieren ließ "
            "den Glow weiterlaufen, und es erschien kein PAUSED-Hinweis. "
            "WE pausiert auf eine Art, die zugleich die Erkennung dafür "
            "stilllegte; der Glow lief weiter, weil er über einen "
            "anderen Kanal kommt. Beides ist behoben.\n"
            "- In Lively hing die Pause nach dem Fortsetzen noch ein bis "
            "zwei Sekunden nach, und der PAUSED-Hinweis erschien beim "
            "*Ent*pausieren statt beim Pausieren. Behoben.\n"
            "- Während ein Spiel im Vordergrund läuft, kostet das "
            "Wallpaper jetzt deutlich weniger: Der Desktopfenster-"
            "Manager wurde mehrmals pro Sekunde geweckt, obwohl alles "
            "pausiert war (gemessen ~2 % CPU, jetzt ~0,3 %).\n\n"
            "**Erfordert einen Re-Import des Wallpaper-Bundles** — die "
            "Änderung steckt in der Wallpaper-Seite. Configurator → "
            "System → *Wallpaper-Bundles neu importieren…*, danach das "
            "Wallpaper in Wallpaper Engine erneut zuweisen. Steam-"
            "Workshop-Abonnenten bekommen es automatisch, sobald der "
            "Eintrag aktualisiert ist.\n"
        ),
    },
    "2.4.3-beta.1": {
        "title_en": "What's new in v2.4.3-beta.1",
        "title_de": "Was ist neu in v2.4.3-beta.1",
        "body_en": (
            "Maintenance beta. No new features — this one is about making "
            "the next bug easier to find and report.\n\n"
            "**Re-import now tells the truth about Workshop copies**\n"
            "- If your wallpaper came from a Steam Workshop subscription, "
            "*Re-import wallpaper bundles* could never update it — that "
            "copy is managed by Steam. It reported success anyway, which "
            "is how the v2.4.2 fix failed to reach the person who "
            "reported the bug it fixed. It now detects the subscription "
            "and tells you what actually works: Steam delivers the "
            "update, then re-apply the wallpaper in Wallpaper Engine.\n\n"
            "**Readable logs**\n"
            "- Every log line now carries a timestamp. Previously there "
            "were none at all, so a diagnostics bundle showed what "
            "happened but not when.\n"
            "- The UDP frame-counter line was firing every few seconds "
            "and had crowded roughly everything else out of the log. It "
            "now appears about once every ten minutes.\n"
            "- The bridge notes when the machine wakes from sleep, so "
            "sleep-related reports are readable at a glance.\n\n"
            "**Under the hood**\n"
            "- Added a regression test-suite (77 checks) covering the "
            "connection lifecycle and the “bridge offline” card, wired "
            "into CI. The v2.4.1/v2.4.2 episode — a bug that took two "
            "releases and one wrong fix — is the reason.\n"
        ),
        "body_de": (
            "Wartungs-Beta. Keine neuen Funktionen — es geht darum, den "
            "nächsten Fehler leichter auffindbar zu machen.\n\n"
            "**Re-Import sagt die Wahrheit über Workshop-Kopien**\n"
            "- Wenn dein Wallpaper aus einem Steam-Workshop-Abo stammt, "
            "konnte *Wallpaper-Bundles neu importieren* es nie "
            "aktualisieren — diese Kopie verwaltet Steam. Trotzdem wurde "
            "Erfolg gemeldet; genau so erreichte der v2.4.2-Fix die "
            "Person nicht, die den behobenen Bug gemeldet hatte. Jetzt "
            "wird das Abo erkannt und der Weg genannt, der wirklich "
            "funktioniert: Steam liefert das Update, danach das "
            "Wallpaper in Wallpaper Engine erneut zuweisen.\n\n"
            "**Lesbare Logs**\n"
            "- Jede Log-Zeile hat jetzt einen Zeitstempel. Vorher gab es "
            "gar keine — ein Diagnose-Paket zeigte, was passiert ist, "
            "aber nicht wann.\n"
            "- Die UDP-Frame-Zählzeile feuerte alle paar Sekunden und "
            "hatte praktisch alles andere aus dem Log verdrängt. Sie "
            "erscheint jetzt etwa alle zehn Minuten.\n"
            "- Die Bridge vermerkt, wenn der Rechner aus dem "
            "Ruhezustand aufwacht — Sleep-Meldungen sind damit auf "
            "einen Blick lesbar.\n\n"
            "**Unter der Haube**\n"
            "- Neue Regressions-Testsuite (77 Checks) für den "
            "Verbindungs-Lebenszyklus und die „Bridge offline\"-Karte, "
            "in die CI eingebunden. Anlass ist die v2.4.1/v2.4.2-"
            "Episode: ein Bug, der zwei Releases und einen falschen Fix "
            "gekostet hat.\n"
        ),
    },
    "2.4.2": {
        "title_en": "What's new in v2.4.2",
        "title_de": "Was ist neu in v2.4.2",
        "body_en": (
            "Fixes the “bridge offline” notification that could stay on "
            "screen after waking the PC from sleep, reported in issue "
            "#2 and tracked down from a user's bridge log.\n\n"
            "**Wallpaper Engine users need one extra step.** The fix is "
            "in the wallpaper page itself, which WE keeps cached. Open "
            "the Configurator, go to **System**, and click **Re-import "
            "wallpaper bundles…**, then re-apply the wallpaper to your "
            "monitor in WE. Lively users are updated automatically by "
            "the same button.\n\n"
            "**What was wrong**\n"
            "- The connection was never broken. Wallpaper Engine "
            "re-delivers the `screenIndex` property when the PC wakes, "
            "which closes and reopens the connection. Each reconnect left "
            "the previous connection's close-handler armed — and when one "
            "of those fired *after* the new connection was already "
            "healthy, it raised the standby card over a working link. "
            "Nothing ever cleared it again, so the card stayed up "
            "indefinitely while frames kept arriving and the canvas kept "
            "rendering.\n"
            "- Stale handlers are now detached on every reconnect, and "
            "late events from superseded connections are ignored.\n"
            "- The card is no longer driven purely by connect/disconnect "
            "events. A reconciler compares it against the real connection "
            "state twice a second, so any missed or out-of-order event "
            "now self-corrects within about half a second instead of "
            "needing a bridge restart.\n"
            "- Added a sleep/resume detector: on wake the reconnect delay "
            "resets to its minimum instead of sitting at the 30-second "
            "ceiling it had backed off to while suspended.\n\n"
            "**Also in this release**\n"
            "- The bridge now pings each connected wallpaper page every "
            "20 s and closes connections that stop answering. This was "
            "first shipped as v2.4.1-beta.1 against a different theory "
            "of issue #2; it turned out not to be the cause, but it "
            "stays in — leaving half-open sockets undetected was wrong "
            "regardless.\n"
        ),
        "body_de": (
            "Behebt die „Bridge offline\"-Benachrichtigung, die nach dem "
            "Aufwachen aus dem Ruhezustand stehen bleiben konnte — "
            "gemeldet in Issue #2 und über das Bridge-Log eines Nutzers "
            "gefunden.\n\n"
            "**Wallpaper-Engine-Nutzer brauchen einen Extra-Schritt.** "
            "Der Fix steckt in der Wallpaper-Seite selbst, die WE "
            "zwischenspeichert. Im Configurator unter **System** auf "
            "**Wallpaper-Bundles neu importieren…** klicken und danach "
            "das Wallpaper in WE erneut zuweisen. Bei Lively erledigt "
            "derselbe Button alles automatisch.\n\n"
            "**Was kaputt war**\n"
            "- Die Verbindung war nie unterbrochen. Wallpaper Engine "
            "liefert beim Aufwachen die `screenIndex`-Property erneut "
            "aus, was die Verbindung schließt und neu öffnet. Jeder "
            "Reconnect ließ den Close-Handler der vorherigen Verbindung "
            "scharf — und wenn einer davon *nach* dem erfolgreichen "
            "Neuaufbau feuerte, blendete er die Standby-Karte über eine "
            "funktionierende Verbindung ein. Etwas, das sie wieder "
            "ausblendet, gab es nicht: Die Karte blieb dauerhaft stehen, "
            "während weiter Frames ankamen und die Canvas lief.\n"
            "- Alte Handler werden jetzt bei jedem Reconnect abgehängt, "
            "und späte Events überholter Verbindungen ignoriert.\n"
            "- Die Karte hängt nicht mehr allein an Connect/Disconnect-"
            "Events: Ein Abgleich prüft zweimal pro Sekunde den echten "
            "Verbindungszustand. Verpasste oder vertauschte Events "
            "korrigieren sich damit in etwa einer halben Sekunde selbst, "
            "statt einen Bridge-Neustart zu brauchen.\n"
            "- Neu: eine Sleep/Resume-Erkennung. Nach dem Aufwachen "
            "springt die Reconnect-Wartezeit auf den Minimalwert zurück, "
            "statt auf den 30 Sekunden zu verharren, auf die sie im "
            "Ruhezustand hochgelaufen war.\n\n"
            "**Ebenfalls in diesem Release**\n"
            "- Die Bridge pingt jetzt alle 20 s jede verbundene "
            "Wallpaper-Seite und schließt Verbindungen, die nicht mehr "
            "antworten. Das kam zuerst als v2.4.1-beta.1 unter einer "
            "anderen Annahme zu Issue #2; sie war nicht die Ursache, "
            "bleibt aber drin — halb offene Sockets unerkannt zu lassen "
            "war ohnehin falsch.\n"
        ),
    },
    "2.4.1-beta.1": {
        "title_en": "What's new in v2.4.1-beta.1",
        "title_de": "Was ist neu in v2.4.1-beta.1",
        "body_en": (
            "Beta build with a fix for the “bridge offline” notification "
            "that stuck around after waking the PC from sleep.\n\n"
            "**Sleep / resume**\n"
            "- After a Windows sleep/resume the local connection between "
            "the bridge and each wallpaper page could come back "
            "half-open: the bridge kept writing frames into a socket "
            "nobody was reading, and neither side ever noticed the other "
            "was gone. The result was a permanent “bridge offline” card "
            "until you restarted the bridge manually.\n"
            "- The bridge now pings every connected wallpaper page every "
            "20 seconds and closes connections that stop answering. A "
            "proper close is what the wallpaper page needs to trigger its "
            "own reconnect, so the notification should now clear on its "
            "own within roughly a minute of waking up.\n"
            "- Also fixed: a client connected to several screens was only "
            "removed from one of them on disconnect, and sockets already "
            "in the process of closing are no longer written to.\n\n"
            "**Testing this**\n"
            "- Please report back if the notification still sticks after "
            "a resume — and roughly how long you waited. The bridge log "
            "(`%LOCALAPPDATA%\\SignalRGBWallpaper\\logs`) now records "
            "`[ws] client idle …` / `keepalive ping failed` lines when it "
            "reaps a dead connection, which tells us whether the new code "
            "fired at all.\n"
        ),
        "body_de": (
            "Beta-Build mit einem Fix für die „Bridge offline\"-"
            "Benachrichtigung, die nach dem Aufwachen aus dem "
            "Ruhezustand hängen blieb.\n\n"
            "**Ruhezustand / Aufwachen**\n"
            "- Nach einem Windows-Sleep/Resume konnte die lokale "
            "Verbindung zwischen Bridge und Wallpaper-Seite halb offen "
            "zurückkommen: Die Bridge schrieb weiter Frames in einen "
            "Socket, den niemand mehr las, und keine Seite bemerkte, "
            "dass die andere weg war. Ergebnis war eine dauerhafte "
            "„Bridge offline\"-Karte, bis man die Bridge manuell neu "
            "startete.\n"
            "- Die Bridge pingt jetzt alle 20 Sekunden jede verbundene "
            "Wallpaper-Seite und schließt Verbindungen, die nicht mehr "
            "antworten. Genau dieses saubere Schließen braucht die "
            "Wallpaper-Seite, um ihren eigenen Reconnect auszulösen — "
            "die Benachrichtigung sollte also innerhalb von etwa einer "
            "Minute nach dem Aufwachen von selbst verschwinden.\n"
            "- Außerdem behoben: Ein Client, der auf mehreren Screens "
            "verbunden war, wurde beim Trennen nur von einem entfernt; "
            "und Sockets, die bereits geschlossen werden, werden nicht "
            "mehr beschrieben.\n\n"
            "**Zum Testen**\n"
            "- Bitte meldet zurück, ob die Benachrichtigung nach einem "
            "Resume weiterhin hängen bleibt — und wie lange ihr ungefähr "
            "gewartet habt. Das Bridge-Log "
            "(`%LOCALAPPDATA%\\SignalRGBWallpaper\\logs`) schreibt jetzt "
            "`[ws] client idle …` / `keepalive ping failed`, wenn eine "
            "tote Verbindung abgeräumt wird — daran sehen wir, ob der "
            "neue Code überhaupt gegriffen hat.\n"
        ),
    },
    "2.4.0": {
        "title_en": "What's new in v2.4.0",
        "title_de": "Was ist neu in v2.4.0",
        "body_en": (
            "Smooth ambient effects on high-refresh monitors, plus clearer "
            "host-compatibility hints in the Configurator.\n\n"
            "**Effects**\n"
            "- The glow grid (Pixel Grid layout) now lands on its own GPU "
            "compositing layer, so the per-frame blur recompute doesn't "
            "block the ambient / pixelfx rAF chains on 144 Hz / 240 Hz "
            "monitors anymore. Same isolation applied to the ambient and "
            "pixelfx canvases.\n"
            "- The Configurator's Grid renderer dropdown now recommends "
            "**Canvas** by default and explains the trade-off: Canvas is "
            "one putImageData call per frame and frees the main thread, "
            "while DOM does up to 1024 style writes per frame and can "
            "stutter on high-refresh setups.\n\n"
            "**Wallpaper Engine compatibility**\n"
            "- Three pixelfx / mousefx effects now carry a “Lively only” "
            "badge in the picker: Hover-Glow, Water-Ripple, and Liquid "
            "Distortion. Wallpaper Engine's bundled CEF doesn't render "
            "the underlying SVG filters and canvas gradients the way "
            "modern Chromium / Lively does, so these stay marked clearly "
            "instead of silently misbehaving in WE.\n\n"
            "**Configurator polish**\n"
            "- This “What's new” modal pops once after each bridge "
            "update; re-open any time via the header button next to "
            "“Tour”.\n"
        ),
        "body_de": (
            "Smoothere Ambient-Effekte auf High-Refresh-Monitoren, plus "
            "klarere Host-Kompatibilitätshinweise im Configurator.\n\n"
            "**Effekte**\n"
            "- Das Glow-Raster (Pixel-Grid-Layout) landet jetzt auf einem "
            "eigenen GPU-Compositing-Layer, damit der per-Frame Blur-"
            "Recompute nicht mehr die Ambient/Pixelfx-rAF-Chains auf "
            "144-Hz/240-Hz-Monitoren blockiert. Selbe Isolation auf den "
            "Ambient- und Pixelfx-Canvases.\n"
            "- Das Grid-Renderer-Dropdown im Configurator empfiehlt jetzt "
            "**Canvas** als Default und erklärt den Trade-off: Canvas "
            "macht ein putImageData pro Frame und entlastet den Main-"
            "Thread, während DOM bis zu 1024 style-writes pro Frame "
            "macht und auf High-Refresh-Setups ruckeln kann.\n\n"
            "**Wallpaper-Engine-Kompatibilität**\n"
            "- Drei Pixelfx/Mousefx-Effekte tragen jetzt ein „Nur "
            "Lively\"-Badge im Picker: Hover-Glow, Wasserwelle und "
            "Flüssige Verzerrung. Die mitgelieferte CEF-Version von "
            "Wallpaper Engine rendert die zugrundeliegenden SVG-Filter "
            "und Canvas-Gradients nicht so wie modernes Chromium / "
            "Lively, deshalb sind diese Effekte jetzt klar markiert "
            "statt in WE still kaputtzugehen.\n\n"
            "**Configurator-Politur**\n"
            "- Dieses „Was ist neu\"-Modal erscheint einmal nach jedem "
            "Bridge-Update; jederzeit wieder öffnen über den Header-"
            "Button neben „Tour\".\n"
        ),
    },
}


def _release_notes_for(version: str) -> dict:
    """Return the {title_*, body_*} dict for the given version, or a
    generic stub if we don't have hand-written notes for it yet.
    Keeps the Configurator code path uniform — it always renders
    something, never nothing."""
    notes = RELEASE_NOTES.get(version)
    if notes:
        return dict(notes, version=version)
    return {
        "version": version,
        "title_en": f"What's new in v{version}",
        "title_de": f"Was ist neu in v{version}",
        "body_en": (
            f"Bridge updated to **v{version}**. Detailed per-commit "
            "release notes are in the full changelog on GitHub — use "
            "the *Open full changelog* button below."
        ),
        "body_de": (
            f"Bridge auf **v{version}** aktualisiert. Detaillierte "
            "Per-Commit-Release-Notes findest du im vollständigen "
            "Changelog auf GitHub — Button *Open full changelog* unten."
        ),
    }

APP_GITHUB_USER = "Delido"
APP_REPO    = f"https://github.com/{APP_GITHUB_USER}/signalrgb-wallpaper"
APP_AUTHOR_URL = f"https://github.com/{APP_GITHUB_USER}"
APP_CREDITS_URL = f"{APP_REPO}/blob/main/docs/credits.md"
APP_DONATE_URL  = "https://paypal.me/SMendyka"

UDP_HOST = "127.0.0.1"
WS_HOST  = "127.0.0.1"


def _port_override(default=17320):
    """The bridge's port, overridable via SIGNALRGB_WP_PORT.

    v2.4.4-beta.14. The port was a hard-coded literal, so a second
    instance could never start: it found 17320 taken, failed to bind and
    exited. That makes a freshly built EXE untestable on a machine where
    the installed one is running — which is every developer machine,
    including the maintainer's. Verifying a build meant killing the
    running bridge and blanking the desktop.

    Deliberately an environment variable rather than a CLI flag: the
    tray, the installer and the Lively/WE bundles all launch the exe
    with no arguments, and a flag none of them pass would only be
    testable by hand. An env var also inherits into whatever the tray
    spawns.

    Out-of-range or non-numeric values fall back to the default instead
    of raising — a typo here should not stop the bridge from starting.
    Ports below 1024 are refused: they need elevation on Windows and
    would fail at bind time with a much less obvious error.
    """
    raw = os.environ.get("SIGNALRGB_WP_PORT", "").strip()
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError:
        print(f"[bridge] SIGNALRGB_WP_PORT={raw!r} is not a number — "
              f"using {default}")
        return default
    if not (1024 <= port <= 65535):
        print(f"[bridge] SIGNALRGB_WP_PORT={port} out of range 1024-65535 — "
              f"using {default}")
        return default
    print(f"[bridge] port overridden to {port} via SIGNALRGB_WP_PORT")
    return port


# UDP and WS share one port; both move together when overridden, and the
# CORS / WS-Origin allowlist below is built from WS_PORT, so a test
# instance keeps the same same-origin guarantees as the real one.
UDP_PORT = _port_override()
WS_PORT  = UDP_PORT

# v1.2.13: lock CORS / WS-Origin to the bridge's own loopback origins.
# Pre-v1.2.13 every endpoint returned `Access-Control-Allow-Origin: *`
# and the WS handshake accepted any Origin. That meant any web page
# the user happened to visit could `fetch("http://127.0.0.1:17320/...")`
# from the background and mutate the wallpaper / settings / library —
# a real one-click-attack surface even though the bridge itself only
# binds to 127.0.0.1. Trust is now per-origin: the Configurator
# served by the bridge (port-bound), the Builder served by the bridge,
# the live-preview iframe (same origin), the Lively / WE WebView2
# `null` origin (file:// pages have an opaque null Origin), and
# explicitly nothing else.
_ALLOWED_HTTP_ORIGINS = frozenset({
    f"http://{WS_HOST}:{WS_PORT}",
    f"http://127.0.0.1:{WS_PORT}",
    f"http://localhost:{WS_PORT}",
    "null",   # file:// + the WebView2 sandbox
})
def _cors_origin_value(origin: bytes | str | None) -> str:
    """Echo back the request's Origin header if it's whitelisted, else
    an empty string (browsers treat that as 'no Allow-Origin', and the
    request is blocked). We deliberately do NOT default to '*' on
    unknown origins.

    The explicit allowlist (_ALLOWED_HTTP_ORIGINS) covers the bridge's
    own loopback URL + `null` for file://-style WebView2 pages. On top
    of that we also accept any host whose name is `127.0.0.1`,
    `localhost`, or a `*.localhost` subdomain — both **Lively** and
    **Wallpaper Engine** serve their WebView2 wallpaper pages from
    a random-hex `<id>.localhost` HTTPS origin
    (e.g. `https://bbeebe4f83f8bc83.localhost`). RFC 6761 reserves
    `.localhost` for loopback, so a remote site can't impersonate
    it — browsers resolve `.localhost` to 127.0.0.1 directly."""
    if not origin:
        return ""
    if isinstance(origin, bytes):
        try: origin = origin.decode("latin-1")
        except Exception: return ""
    origin = origin.strip()
    if origin in _ALLOWED_HTTP_ORIGINS:
        return origin
    try:
        parsed = urllib.parse.urlparse(origin)
        host = (parsed.hostname or "").lower()
        if host == "127.0.0.1" or host == "localhost" or host.endswith(".localhost"):
            return origin
    except Exception:
        pass
    return ""

# Max payload size accepted on POST /screen/<N>/background. Generous (50 MB)
# but bounded — the builder caps output well below this in practice.
MAX_BACKGROUND_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB — generous to leave room for video uploads (10-30s 1080p MP4 = 20-80 MB; 4K loops can reach 150 MB)

WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_SCREEN_INDEX = 7  # generous upper bound; plugin caps at 3 (4 screens)
N_SCREENS = 4

CONFIG_VERSION = 1
DEFAULT_SCREEN_SETTINGS = {
    "bgImage":      "",
    "bgImageUrl":   "",
    "bgFit":        "cover",
    # Pattern scale for the tile / tile-x / tile-y bgFit modes (10-200,
    # percent). 100 = native source size. Ignored when bgFit is
    # cover/contain/fill since those modes already define the
    # background-size implicitly.
    "bgTileScale":  100,
    "bgDim":        0,
    "barLayout":    "lay-grid",
    "showBars":     True,
    "glowStrength": 100,
    "gridBlur":     30,
    # v1.2.12: which grid-layout renderer the wallpaper page should
    # use — "dom" (one solid-colour <div> per zone) or "canvas"
    # (single <canvas> + putImageData). v1.5.0-beta switches the
    # default to "canvas" after a real-hardware perf trace from a
    # 5120×1440 user showed the DOM path producing 1.3 M Paint
    # events in 7.8 s (~115 k paints/sec — 3,800+ DIV zones at the
    # broadcast rate). Canvas is one putImageData per frame
    # regardless of grid size, so it scales cleanly with the
    # SignalRGB grid resolution. Users on tiny grids or specific
    # dGPU setups where DOM was cheaper can still flip back in
    # the Configurator's per-screen Glow card.
    #
    # v2.4.6 added a "canvas-prescale" value — larger backing buffer,
    # proportionally smaller CSS blur — on the strength of a -23 %
    # Canvas 2D benchmark. Measured on the real page it made no
    # difference at all (median 5.3 % vs 4.5 %, inside the run-to-run
    # spread), because the shipped blur is a CSS filter on a composited
    # layer and Chromium already downsamples wide radii internally.
    # v2.4.7 removed it again. The grid blur turned out not to cost
    # anything measurable in the first place: switching the whole glow
    # grid off on a 5120×1440 span moved the needle 2.24 % -> 2.42 %,
    # i.e. not at all.
    "gridRenderer": "canvas",
    # v1.2.12: render-rate cap shared by the bridge's outgoing
    # broadcast and the wallpaper page's renderFrame gate. SignalRGB
    # sends UDP at whatever rate it can compute (often 100-200 fps
    # for cheap effects); for a blurred glow layer 30 Hz is
    # perceptually identical to 60 Hz, so capping there saves both
    # halves of the pipeline. Three buckets:
    #   20 → "Performance" — biggest CPU win, slight latency
    #   30 → "Balanced" (default) — visually indistinguishable from
    #        60 Hz on the blurred glow layer
    #   60 → "Quality"     — matches the plugin's typical rate
    "frameRate": 30,
    # v1.6.3-beta: effect-canvas quality bucket. Controls the backing-
    # buffer resolution + DPR of the three full-viewport effect
    # canvases (#ambient-canvas, #pixelfx-canvas, #audioglow-canvas).
    # The v1.6.1-beta GPU sweep dropped DPR to 1 + halved the ambient
    # resolution to reach 0% idle on a 5120×1440 setup — that's the
    # right floor for "I'm idle, don't burn the GPU", but users on
    # heavier hardware want the option to crank the quality back up
    # for active sessions. Three buckets:
    #   "performance" → 0.5× ambient backing, DPR 1, 30 Hz cap.
    #                   Matches v1.6.1-beta's GPU sweep defaults.
    #   "balanced"    → 0.75× ambient backing, DPR 1, 30 Hz.
    #                   Middle ground; softer than performance,
    #                   ~half the GPU of quality.
    #   "quality"     → 1.0× ambient backing, DPR up to 2, 60 Hz.
    #                   Pre-v1.6.1-beta visual fidelity; expect 3-4×
    #                   the GPU of performance on a 5120×1440 surface.
    # Stays "performance" for new installs so the perf-sweep gains
    # don't regress silently when users upgrade.
    "effectQuality": "performance",
    # v1.2.12: glass-tile backdrop-filter quality. Per-widget
    # backdrop-filter is the single most expensive GPU op on the
    # page; the radius cost is quadratic. Three buckets:
    #   • "low"    → backdrop-filter: none + slightly higher alpha
    #     on the bg so the glass shape still reads. Saves the most
    #     GPU; visual is solid-tinted.
    #   • "medium" → backdrop-filter: blur(6px) saturate(140%).
    #     Default. Drops cost ~4× from v1.2.11's 12px while keeping
    #     the glassy feel.
    #   • "high"   → backdrop-filter: blur(12px) saturate(140%).
    #     Restores pre-v1.2.12 quality for users on heavy GPUs.
    # Only applies when a widget is in the Glass tile style.
    "glassQuality": "medium",
    "stripesBlur":  60,
    "barHeight":    38,
    "barWidth":     14,
    "showStatus":   False,
    # Placeable HTML widgets (clock / calendar / weather, more coming).
    # Each entry: {"id":"w_<int>", "type":"clock|calendar|weather",
    #              "x":int, "y":int, "w":int, "h":int,
    #              "options": {…}}. Positions are CSS pixels relative to
    #              the wallpaper page's viewport.
    "widgets":         [],
    # When True the wallpaper renders widgets read-only. When False the
    # wallpaper attaches drag/resize handles (via interact.js) and pushes
    # position updates back over the WS as widget-update messages.
    "widgetsLocked":   True,
    # Optional unified "tile" shell wrapping every widget (post-v1.0
    # design-system refresh). One of "off" | "glass" | "solid" | "clear".
    # Default "off" preserves the v1.0 transparent-overlay look every
    # existing user is already running.
    "widgetTileStyle": "off",
    # v1.6.0-beta: theme palette applied across every widget. Each
    # theme is a set of CSS variables (background, border, primary
    # text, secondary text, accent, font stack) defined under a
    # body.theme-<name> class in wallpaper/index.html. Stacks with
    # widgetTileStyle (style = container chrome; theme = colours +
    # typography). One of:
    #   "default" | "dracula" | "nord" | "tokyo-night" |
    #   "catppuccin" | "solarized" | "vintage-crt" | "light"
    "widgetTheme":     "default",
    # Full-canvas ambient effect (Phase 2). One of:
    #   "off" | "snow" | "rain" | "sparks" | "aurora"
    "ambientEffect":   "off",
    # When True the ambient effect samples the live glow colour and tints
    # particles accordingly (snow → wallpaper-coloured, etc.). Off by default
    # so snow stays white / rain stays bluish.
    "ambientTint":     False,
    # 1..100 — relative particle count / saturation knob.
    "ambientDensity":  60,
    # v2.3.3-beta: when True, the Weather widget's WMO code overrides
    # the ambient preset at runtime — rain code → rain particles, snow
    # code → snow, thunderstorm → storm. The override is presentation-
    # only; ambientEffect (the user's pick) stays untouched and is
    # restored the moment this is flipped back off.
    "weatherReactiveAmbient": False,
    # Cursor / click eye-candy (Phase 4). One of:
    #   "off" | "trail" | "glow" | "ripple" | "all"
    # Position arrives via Lively's livelyCurrentCursorPos callback so the
    # trail works even with click-through enabled; ripples need real clicks
    # (Lively interaction must be on).
    "pixelfx":         "off",
    # v1.6.0-beta: stackable mouse-driven distortion effects, parallel
    # to the existing pixelfx single-select. Array of any of:
    #   "repulsion"       — widgets ease away from the cursor
    #   "chromatic"       — glow zones near the cursor split R/G/B
    #   "spotlight"       — radial cone follows cursor (vignette inverse)
    #   "ripple"          — SVG feDisplacementMap-driven liquid distortion
    # All four can run concurrently — each one is opt-in and uses its
    # own rAF chain or static SVG filter. Empty array = none active.
    "mouseEffects":    [],
    # Parallax 3D — when > 0 the background image translates a fraction
    # of the cursor offset (smooth lerp), creating a fake-depth effect.
    # Value is the maximum displacement in CSS pixels at the cursor's
    # most extreme corner. 0 = off (default). 30 is gentle, 80 is strong.
    "parallax3d":      0,
    # Whole-screen audio-reactive glow layer. Driven by the same FFT data
    # the audio-spectrum widget already drains (Lively's
    # livelyAudioListener / WE's wallpaperRegisterAudioListener).
    # Modes: "off" | "pulse" | "spectrum" | "wave".
    "audioGlow":            "off",
    "audioGlowIntensity":   60,    # 0..100
    "audioGlowTint":        False, # tint with the live glow-feed average
    # Last known viewport reported by the wallpaper page itself (in CSS
    # pixels). The bridge can't ask Windows directly because each page
    # lives on whichever monitor Lively / WE assigns it; the page knows.
    # Used by the configurator's layout-preview to scale to the real
    # screen instead of guessing FullHD. 0 = not yet reported.
    "viewportW":       0,
    "viewportH":       0,
    # Per-screen preset slots. Each slot is either None (empty) or a
    # snapshot dict of every settable screen key (see PRESET_SNAPSHOT_KEYS
    # below). The Configurator surfaces N slot buttons; Save captures the
    # current state, Apply writes the snapshot back into the screen's
    # settings, Clear sets the slot to None.
    "presets":         [None, None, None, None],
    # Mirror mode: when set to another screen index, this screen's settings
    # are kept in lockstep with that screen's. The bridge:
    #   - copies all mirrorable keys from the source on activation
    #   - replicates every per-screen mutation of the source to the mirror
    #   - rejects direct mutations of the mirror (read-only)
    # `None` means "not mirroring". Self-mirror and chains (A→B→C) are
    # rejected at the WS / HTTP entry point.
    "mirrorOf":        None,
    # Auto-cycle through library entries on a schedule. When enabled,
    # CycleScheduler picks the next pool entry every `intervalMin` minutes
    # and applies it as the screen's background via _update_background.
    # `pool` is one of "all" | "pinned"; `order` is "sequential" | "random".
    # `lastApplyMs` / `nextIdx` are managed by the scheduler — exposed in
    # the config so they survive a restart.
    "cycle":           {
        "enabled":     False,
        "intervalMin": 10,
        "pool":        "all",
        "order":       "sequential",
        "lastApplyMs": 0,
        "nextIdx":     0,
    },
    # v1.2.8: Builder Monitor-Setup. Declares how the bridge-reported
    # viewport actually splits into physical monitors so the Builder's
    # Wall + composite-Apply use the right per-tile dimensions.
    #   mode          "single" | "span-h" | "span-v"
    #   orientations  per sub-tile, either "landscape" or "portrait".
    #                 Length always matches mode's tile count (1 for
    #                 single, 2 for span-h/-v). Portrait sub-tiles get
    #                 a 90° CW rotation when composited into the bridge
    #                 slot. Single mode is always landscape (no swap).
    # Editable from the Configurator's screen-popover; Builder reads
    # it via the WS settings push instead of its old localStorage copy.
    "monitorSetup":    {
        "mode":         "single",
        "orientations": ["landscape"],
    },
}

# Keys that get replicated to mirror screens. Per-screen physical
# attributes (viewport, mirrorOf itself) stay independent, otherwise
# the mirror would lose its identity. Presets aren't mirrored because
# they're user-curated per-screen scratch space. `cycle` isn't mirrored
# — only the source's cycle runs; the mirror inherits the resulting
# bgImage change through the existing replication path.
_NON_MIRRORED_KEYS = frozenset({
    "viewportW", "viewportH", "mirrorOf", "presets", "cycle",
    # monitorSetup describes the *physical* monitor layout per bridge
    # screen — it's a property of the user's hardware, not a display
    # setting. Mirroring would copy the source's span declaration onto
    # the mirror, which has its own physical wiring.
    "monitorSetup",
})

# Keys that get rolled up into a preset snapshot. Excludes anything the
# wallpaper page reports back (viewports), anything transient (locks), and
# the preset list itself (so a preset can't recursively contain its
# siblings).
PRESET_SNAPSHOT_KEYS = (
    "bgImage", "bgImageUrl", "bgFit", "bgTileScale", "bgDim",
    "barLayout", "showBars", "glowStrength",
    "gridBlur", "stripesBlur", "barHeight", "barWidth",
    "showStatus",
    "widgets", "widgetTileStyle",
    # v1.6.1-beta R2.2: v1.6 aesthetic settings that the audit caught
    # as silently dropped from save/apply. widgetTheme = palette
    # (Dracula / Nord / CRT / …); mouseEffects = the stackable
    # cursor-driven distortion array (repulsion / chromatic / spotlight
    # / ripple). Older saved presets simply don't carry these keys —
    # apply_preset's `if k in snapshot` guard leaves the live value
    # alone, so existing slots stay valid.
    "widgetTheme", "mouseEffects",
    # v1.6.3-beta hotfix1: effectQuality bucket. Travels with
    # presets so a user's "Cinema preset = Quality" / "Idle preset =
    # Performance" intent survives Save/Apply. frameRate / glassQuality
    # / gridRenderer stay excluded — those are hardware-perf knobs
    # the user picks once for their machine; effectQuality is the
    # aesthetic-perf trade and reasonably scoped per preset.
    "effectQuality",
    "ambientEffect", "ambientTint", "ambientDensity",
    "pixelfx", "parallax3d",
    "audioGlow", "audioGlowIntensity", "audioGlowTint",
)
# v1.6.1-beta R2.2: user-configuration subset of the `cycle` dict that
# travels with a preset. Runtime state (lastApplyMs, nextIdx) stays
# live across Apply so the rotation keeps its current position
# instead of jumping back to the snapshot's frozen index.
PRESET_CYCLE_SUBKEYS = ("enabled", "intervalMin", "pool", "order")
PRESET_SLOTS = 4

# Server-side schemas for widget option defaults — keep in sync with the
# wallpaper-page renderers. Tray "Add widget" uses these to seed a fresh
# entry; client-side options editor (later) writes back through the same
# WS protocol.
# Each entry: position + size at spawn, the type-specific options blob, and
# a tray-menu label. The wallpaper page mirrors the keys in its WIDGET_REGISTRY
# so the in-page picker and the tray "Add…" submenu both stay in sync.
WIDGET_DEFAULTS = {
    "clock": {
        "label":   "Clock",
        "x": 60, "y": 60, "w": 220, "h": 220,
        "options": {"style": "analog", "format24h": True, "tintFromGlow": False},
    },
    "calendar": {
        "label":   "Calendar",
        "x": 60, "y": 320, "w": 260, "h": 240,
        "options": {"tintFromGlow": False, "weekStart": 1},   # 0=Sun, 1=Mon
    },
    "weather": {
        "label":   "Weather",
        "x": 60, "y": 600, "w": 240, "h": 140,
        # v2.3.4-beta: `skin` = "default" picks the redesigned layout
        # that shipped in v2.3.3-beta. "compact" / "hexagon" are the
        # bundled alternates — see WIDGET_REGISTRY.weather.skins in
        # wallpaper/index.html for the actual markup + render fns.
        "options": {"lat": 52.52, "lon": 13.405, "label": "Berlin",
                    "units": "metric", "skin": "default",
                    "tintFromGlow": False},
    },
    "sticky-note": {
        "label":   "Sticky note",
        "x": 340, "y": 60, "w": 220, "h": 180,
        "options": {"text": "Double-click in edit mode to write a note.",
                    "color": "yellow", "tintFromGlow": False},
    },
    "countdown": {
        "label":   "Countdown",
        "x": 340, "y": 280, "w": 240, "h": 140,
        # Target gets seeded by the wallpaper page on first render (we
        # can't sensibly hardcode a date in this Python file). Empty
        # string here means "use today + 30 days as default".
        "options": {"target": "", "label": "Event",
                    "units": "smart", "tintFromGlow": False},
    },
    "picture-frame": {
        "label":   "Picture frame",
        "x": 340, "y": 460, "w": 260, "h": 200,
        "options": {"url": "", "fit": "cover", "rounded": True,
                    "tintFromGlow": False},
    },
    "quote": {
        "label":   "Quote of the day",
        "x": 600, "y": 60,  "w": 320, "h": 180,
        "options": {"source": "quotable", "tintFromGlow": False},
    },
    "cpu-meter": {
        "label":   "CPU meter",
        "x": 600, "y": 260, "w": 200, "h": 140,
        "options": {"tintFromGlow": False},
    },
    "ram-meter": {
        "label":   "RAM meter",
        "x": 600, "y": 420, "w": 200, "h": 140,
        "options": {"tintFromGlow": False},
    },
    "audio-spectrum": {
        "label":   "Audio spectrum",
        "x": 820, "y": 440, "w": 280, "h": 120,
        "options": {"tintFromGlow": False},
    },
    # Generic LibreHardwareMonitor-driven sensor display. Empty
    # sensorPath = blank widget on the wallpaper; user opens the
    # Configurator's options modal to pick a sensor from the dropdown
    # populated by /hwmon/sensors. Decimals defaults to 1 (good for
    # temps in °C and most voltages); explicit label override is empty
    # so the widget falls back to the sensor's leaf-segment as label.
    "hardware-sensor": {
        "label":   "Hardware sensor",
        "x": 600, "y": 580, "w": 220, "h": 140,
        "options": {"sensorPath": "", "label": "", "decimals": 1,
                    "tintFromGlow": False},
    },
    # Now-playing widget — reads the live media session published by
    # NowPlayingPoller (Windows SMTC). Shows title + artist + a thin
    # progress bar; auto-hides itself when no media session is active.
    "now-playing": {
        "label":   "Now playing",
        "x": 1100, "y": 580, "w": 320, "h": 96,
        "options": {"showProgress": True, "showArtist": True,
                    "tintFromGlow": False},
    },
    # RSS / Atom feed reader. Fetches a user-configured feedUrl every
    # refreshMin minutes inside the wallpaper page (we don't proxy
    # through the bridge — the feed source's CORS / cache headers
    # apply directly). Defaults: empty URL = shows "Click ⚙ to set a
    # feed URL" placeholder; 15-min refresh; 8 visible items.
    "rss": {
        "label":   "RSS feed",
        "x": 1100, "y": 60, "w": 360, "h": 280,
        "options": {"feedUrl": "", "feedTitle": "",
                    "itemCount": 8, "refreshMin": 15,
                    "showDate": True, "tintFromGlow": False},
    },
    # v1.5.0-beta: generic HTTP widget. Polls a user-configured URL
    # every refreshMin minutes, parses JSON if the Content-Type says
    # so (else treats as text), and renders the value via a tiny
    # mustache-flavoured template (`{{path.to.field}}` substitutions).
    # Covers Discord-unread / stock-ticker / RSS-headline /
    # crypto-price / arbitrary REST API with ONE widget type instead
    # of one widget per service. Lives on the wallpaper page (no
    # bridge proxy) — the target's CORS + cache headers apply
    # directly, same as the RSS widget.
    "http": {
        "label":   "Custom HTTP",
        "x": 1100, "y": 360, "w": 360, "h": 160,
        "options": {
            "url":           "",
            "method":        "GET",
            "headers":       "",   # one "Key: value" pair per line
            "title":         "",
            "template":      "{{.}}",
            "refreshMin":    5,
            "tintFromGlow":  False,
        },
    },
}
if not ENABLE_NOWPLAYING:
    WIDGET_DEFAULTS.pop("now-playing", None)
WIDGET_TYPES = list(WIDGET_DEFAULTS.keys())

# Choices that must match the wallpaper HTML / CSS class names.
BG_FIT_CHOICES   = ["cover", "contain", "fill", "tile", "tile-x", "tile-y"]
LAYOUT_CHOICES   = [
    ("lay-grid",     "Pixel Grid (2D)"),
    ("lay-vstripes", "Vertical Stripes"),
    ("lay-hstripes", "Horizontal Stripes"),
    ("lay-pills",    "Centered Pills"),
    ("lay-off",      "Hidden (image only)"),
]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}
# v1.2.6: the /image proxy must also serve the video containers the
# wallpaper page's <video> bg element plays — a video set as a screen
# background lands as screens\screen-N-*.mp4 and the wallpaper page
# routes it through /image?path= just like an image. Pre-v1.2.6 the
# proxy rejected these extensions with 415, so video backgrounds set
# via the Builder / library never actually loaded on the wallpaper.
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".mkv"}
SERVABLE_EXTS = IMAGE_EXTS | VIDEO_EXTS
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/webp",   ".webp")
mimetypes.add_type("video/mp4",    ".m4v")
mimetypes.add_type("video/x-matroska", ".mkv")
mimetypes.add_type("video/quicktime",  ".mov")


# ============================================================================
# Config: load / save / defaults
# ============================================================================

def config_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    folder = Path(base) / "SignalRGBWallpaper"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "config.json"


def _candidate_documents_dirs() -> list[Path]:
    """Every plausible location for the user's "Documents" folder, in
    preference order. Windows redirects Documents to OneDrive on a lot
    of installs — `Path.home() / "Documents"` will exist but be empty
    when that happens, while Inno Setup's `{userdocs}` token routes
    through `SHGetFolderPath(CSIDL_PERSONAL)` and writes to the actual
    OneDrive-backed path. We mirror that resolution here so the
    System-status dialog finds the plugin file in the same place the
    installer dropped it.

    Order:
      1. HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\
         Shell Folders\\Personal — authoritative, matches `{userdocs}`
      2. Detected `~/OneDrive*/Documents` and `~/OneDrive*/Dokumente`
         siblings for users where the registry value lags a sync
      3. Plain `~/Documents` / `~/Dokumente` as the legacy fallback
    """
    seen: set[str] = set()
    out: list[Path] = []
    def add(p: Path | None):
        if p is None:
            return
        try:
            resolved = p.resolve()
        except Exception:
            resolved = p
        key = str(resolved).lower()
        if key in seen:
            return
        seen.add(key)
        out.append(resolved)

    # 1) Registry "Personal" value — the one Windows itself uses.
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        ) as k:
            value, _ = winreg.QueryValueEx(k, "Personal")
            add(Path(os.path.expandvars(value)))
    except Exception:
        pass
    # User Shell Folders carries the unexpanded version (with env vars
    # like %USERPROFILE%) which can be more accurate when the cache
    # in Shell Folders is stale.
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as k:
            value, _ = winreg.QueryValueEx(k, "Personal")
            add(Path(os.path.expandvars(value)))
    except Exception:
        pass

    # 2) Any OneDrive root under the home folder (personal + corp).
    try:
        home = Path.home()
        for child in home.iterdir():
            name = child.name
            if name.lower().startswith("onedrive") and child.is_dir():
                for doc_name in ("Documents", "Dokumente"):
                    cand = child / doc_name
                    if cand.is_dir():
                        add(cand)
    except Exception:
        pass

    # 3) Plain home/Documents and the German variant.
    for doc_name in ("Documents", "Dokumente"):
        add(Path.home() / doc_name)

    return out


def screens_dir() -> Path:
    """Where builder-uploaded backgrounds get persisted, one file per
    screen with a unix-millis timestamp suffix so the browser can't cache
    a stale image after re-upload."""
    p = config_path().parent / "screens"
    p.mkdir(parents=True, exist_ok=True)
    return p


_LIBRARY_SAFE_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789-_"

def _library_slug(label: str, lib: Path) -> str:
    """Make a filesystem-safe slug from a user-provided label, avoiding
    collisions with existing files in `lib`. Trimmed to 60 chars."""
    s = "".join(c if c in _LIBRARY_SAFE_CHARS else "-" for c in (label or "").lower())
    while "--" in s: s = s.replace("--", "-")
    s = s.strip("-") or "untitled"
    s = s[:60]
    base = s
    i = 2
    # v1.2-dev: extension list extended to cover GIF + video so a
    # "spaceship.mp4" upload doesn't collide with an earlier
    # "spaceship.png" of the same slug.
    while any((lib / (base + ext)).exists() for ext in
              (".png", ".jpg", ".jpeg", ".webp", ".gif",
               ".mp4", ".webm", ".mov", ".m4v", ".mkv")):
        base = f"{s}-{i}"
        i += 1
    return base


# v1.7.5: runtime fallback for tag-less entries. Mirrors the build-time
# `_TAG_RULES` in installer/generate_library.py — kept here so an
# upgrade install (where library.json carries `onlyifdoesntexist` and
# the shipped catalogue is never written) still surfaces meaningful
# tag chips on bundled items.
_BRIDGE_TAG_RULES = {
    "cyberpunk":      ["cyberpunk", "neon", "night"],
    "neon":           ["neon", "night"],
    "aurora":         ["aurora", "nature", "night"],
    "synthwave":      ["synthwave", "retro"],
    "tokyo":          ["cyberpunk", "neon", "night", "asian"],
    "rgb":            ["rgb", "gaming", "interior"],
    "skyline":        ["skyline", "city"],
    "city":           ["city"],
    "street":         ["street", "city"],
    "alley":          ["street", "city"],
    "boulevard":      ["street", "city"],
    "backstreet":     ["street", "city"],
    "highway":        ["street", "city"],
    "storefront":     ["street", "city"],
    "vista":          ["city"],
    "holo":           ["cyberpunk", "futuristic"],
    "setup":          ["rgb", "gaming"],
    "studio":         ["rgb", "gaming"],
    "abstract":       ["abstract"],
    "curve":          ["abstract"],
    "geometric":      ["abstract"],
    "panels":         ["abstract"],
    "grid":           ["synthwave", "abstract"],
    "anime":          ["anime"],
    "window":         ["abstract"],
    "mountains":      ["synthwave", "nature"],
    "horizon":        ["synthwave"],
    "sun":            ["synthwave"],
    "pines":          ["nature"],
    "sky":            ["nature"],
    "night":          ["night"],
    "wet":            ["street", "city"],
    "pink":           ["neon"],
    "underwater":     ["underwater", "nature"],
    "jellies":        ["underwater", "nature"],
    "sea":            ["underwater", "nature"],
    "bioluminescent": ["bioluminescent", "nature"],
    "mushroom":       ["bioluminescent", "nature"],
    "forest":         ["nature"],
    "grove":          ["nature"],
    "spaceship":      ["scifi", "futuristic", "interior"],
    "stellar":        ["scifi", "abstract"],
    "quantum":        ["abstract"],
    "plasma":         ["abstract"],
    "web":            ["abstract"],
    "burst":          ["abstract"],
    "wave":           ["abstract"],
    "twin":           ["cyberpunk", "city"],
    "towers":         ["cyberpunk", "city"],
    "cyan":           ["cyberpunk"],
    "magenta":        ["neon"],
    "foggy":          ["night"],
    "bridge":         ["scifi"],
    "curtain":        ["aurora", "nature"],
    "rainy":          ["street"],
    "futuristic":     ["futuristic", "scifi"],
}


def _tags_for_slug_bridge(slug: str) -> list[str]:
    parts = set(slug.lower().split("-"))
    tags: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for taglist in _BRIDGE_TAG_RULES.get(part, ()):
            if taglist not in seen:
                seen.add(taglist)
                tags.append(taglist)
    return tags


# v2.2.2: atomic write + RLock guarding the library.json read-modify-
# write sequence. Pre-v2.2.2 the rebuild + update_item + apply_order
# paths all did `cat_path.write_text(...)` directly. Two problems:
#   1. A crash mid-write leaves an empty / truncated library.json
#      which the next bridge start can't parse → empty Library tab.
#   2. v2.2.0 moved the heavy autocut / transform work into a thread
#      executor. That thread + the asyncio main loop can both hit
#      library.json simultaneously (e.g. user pins an entry while an
#      autocut upload finishes). The later writer wins; the earlier
#      mutation gets silently overwritten. Latent silent data loss.
# `save_config` already used the tmp + replace pattern for config.json;
# this lifts the same approach to library.json + adds an explicit
# lock so the executor + main loop serialise on every catalogue
# mutation.
_LIBRARY_LOCK = threading.RLock()


def _library_write_atomic(cat_path: Path, payload: dict) -> None:
    """Write library.json atomically: dump to a sibling .tmp, then
    rename over the target. The rename is atomic on every modern
    filesystem (NTFS / ReFS / ext4 / APFS), so a reader concurrent
    with the write sees either the old file or the new — never a
    half-written one."""
    tmp = cat_path.with_suffix(cat_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(cat_path)


def _library_rebuild_catalogue(lib: Path) -> None:
    """Rescan the library folder and rewrite library.json with one entry
    per image. Files matching `<stem>.thumb.png` are paired as thumbs
    with their main image; everything else becomes a tile without an
    explicit thumb (the Configurator falls back to the main file).

    User-state fields (`pinned`, `order`, `addedAt`) are preserved from
    the previous catalogue if the file still exists — that way an
    upload/delete/rename doesn't wipe the user's pin and drag-reorder
    state. `addedAt` is initialised from file mtime for new entries so
    "sort by newest first" works out of the box for fresh uploads."""
    with _LIBRARY_LOCK:
        _library_rebuild_catalogue_locked(lib)


def _library_rebuild_catalogue_locked(lib: Path) -> None:
    """Body of _library_rebuild_catalogue without the lock — for
    internal callers that already hold _LIBRARY_LOCK."""
    prev_by_file: dict[str, dict] = {}
    cat_path = lib / "library.json"
    if cat_path.exists():
        try:
            prev = json.loads(cat_path.read_text(encoding="utf-8"))
            for it in prev.get("items", []):
                if isinstance(it, dict) and "file" in it:
                    prev_by_file[it["file"]] = it
        except Exception:
            pass

    items = []
    # GIF + video extensions added in v1.2-dev — wallpaper page now
    # routes any *.mp4 / *.webm / *.mov / *.m4v / *.mkv through a
    # <video> element instead of the image-div. GIFs already animated
    # via the CSS background-image path; they're listed here because
    # the library catalogue is what populates the Configurator's
    # picker strip.
    files = sorted([p for p in lib.iterdir()
                    if p.is_file() and p.suffix.lower() in
                    (".png", ".jpg", ".jpeg", ".webp", ".gif",
                     ".mp4", ".webm", ".mov", ".m4v", ".mkv")])
    stems = {p.name for p in files}
    # v1.7.5: dedup by stem so a stem present as both `<stem>.png` and
    # `<stem>.webp` (typical upgrade path: v1.7.4 shipped PNGs, v1.7.5
    # ships WebP — Inno only adds files so both linger on disk until
    # the user manually cleans) collapses into ONE entry. Preference:
    # webp > avif > png > jpg > jpeg > everything else. The
    # [InstallDelete] block in the .iss also wipes the known legacy
    # PNG slugs on install so the duplicates disappear on first
    # upgrade — this is the defence-in-depth path for any future
    # extension change.
    _ext_priority = {".webp": 0, ".avif": 1, ".png": 2, ".jpg": 3,
                     ".jpeg": 3, ".gif": 4}
    _by_stem: dict[str, Path] = {}
    for fp in files:
        stem = fp.stem
        # v1.7.5: skip thumb + 4K siblings — they're paired with
        # their parent slug later.
        if stem.endswith(".thumb") or stem.endswith(".4k"):
            continue
        current = _by_stem.get(stem)
        if current is None:
            _by_stem[stem] = fp
            continue
        cur_prio = _ext_priority.get(current.suffix.lower(), 99)
        new_prio = _ext_priority.get(fp.suffix.lower(), 99)
        if new_prio < cur_prio:
            _by_stem[stem] = fp
    files = sorted(_by_stem.values())
    stems = {p.name for p in lib.iterdir() if p.is_file()}
    for fp in files:
        stem = fp.stem
        if stem.endswith(".thumb") or stem.endswith(".4k"):
            continue
        thumb = None
        for cand in (stem + ".thumb.png", stem + ".thumb.jpg", stem + ".thumb.webp"):
            if cand in stems:
                thumb = cand
                break
        # v1.7.5: 4K sibling — same logic as thumb. Optional; if
        # absent, library.json entry omits `file4k` and the
        # Configurator falls back to the FHD file.
        file4k = None
        for cand in (stem + ".4k.webp", stem + ".4k.png", stem + ".4k.jpg"):
            if cand in stems:
                file4k = cand
                break
        prev_it = prev_by_file.get(fp.name) or {}
        try:
            added_at_default = int(fp.stat().st_mtime * 1000)
        except OSError:
            added_at_default = int(time.time() * 1000)
        # v1.7.5: mtime per file (main + thumb) so the configurator
        # can append ?v=<mtime> to the URL it renders. Without this
        # the CEF cache happily reuses old thumb bytes after a
        # bundle regen — the same file path returns different
        # content but the URL is identical, so the browser never
        # re-fetches. With ?v= different, the cache key differs.
        try:
            mtime_main = int(fp.stat().st_mtime * 1000)
        except OSError:
            mtime_main = added_at_default
        mtime_thumb = mtime_main
        if thumb:
            try:
                mtime_thumb = int((lib / thumb).stat().st_mtime * 1000)
            except OSError:
                pass
        # v1.6.1-beta library categories: "background" (suitable for
        # the wallpaper / auto-cycle pool), "template" (Builder
        # source material — not meant to be shown raw), "both".
        # v1.7.5: default changed from "both" to "background". Real-
        # world: ~95 % of user uploads + every bundled / generated
        # image is a finished wallpaper, not a Builder source. The
        # old default surfaced every uncategorised image in BOTH
        # filter chips ("Hintergründe" + "Vorlagen"), which made
        # the Vorlagen chip useless. "background" is the safer
        # default; users who actually edit images in the Builder
        # set "template" explicitly via the per-entry right-click.
        category = prev_it.get("category") or "background"
        if category not in ("background", "template", "both"):
            category = "background"
        entry = {
            "id":       stem,
            "label":    stem.replace("-", " ").replace("_", " ").title(),
            "file":     fp.name,
            "thumb":    thumb or fp.name,
            "mtime":    mtime_main,
            "mtimeThumb": mtime_thumb,
            "pinned":   bool(prev_it.get("pinned", False)),
            "category": category,
            "order":    prev_it.get("order"),
            "addedAt":  prev_it.get("addedAt", added_at_default),
        }
        if file4k:
            entry["file4k"] = file4k
        # v1.7.5: preserve user-curated `tags` (string list) through
        # the rebuild so the Library tab's chip filter stays stable
        # across bridge restarts + uploads. Generator-produced
        # tags for bundled items also live in this field; the
        # rebuild keeps whatever was there.
        prev_tags = prev_it.get("tags")
        if isinstance(prev_tags, list) and prev_tags:
            entry["tags"] = [str(t)[:32] for t in prev_tags
                              if isinstance(t, str) and t.strip()]
        else:
            # v1.7.5: no prev tags — derive from slug so bundled items
            # surface meaningful chips on first run AND on upgrades
            # where the shipped library.json never overwrites the
            # user's existing one (onlyifdoesntexist Inno flag).
            derived = _tags_for_slug_bridge(stem)
            if derived:
                entry["tags"] = derived
        # v1.7.5 wave 2: preserve `pack` so per-pack filter chips
        # in the Library tab survive a catalogue rebuild (uploads,
        # rename, app restart). Bundled essentials get `pack:
        # "bundled"` written by generate_library.py; pack installs
        # tag their slugs in install_library_pack.
        prev_pack = prev_it.get("pack")
        if isinstance(prev_pack, str) and prev_pack.strip():
            entry["pack"] = prev_pack.strip()[:32]
            # v2.3.0-beta hotfix: pack_version was preserved INFORMALLY
            # by only persisting it on the pack we'd most recently
            # installed — every catalogue rebuild stripped the version
            # off older packs. `_packs_installed_state` keys off
            # pack_version > 0 to decide which packs are installed, so
            # the older packs silently flipped back to "Laden" in the
            # UI after each new install. Preserve it here so multiple
            # packs can be installed at once and the UI keeps showing
            # all of them as installed.
            prev_ver = prev_it.get("pack_version")
            try:
                pv = int(prev_ver) if prev_ver is not None else 0
            except Exception:
                pv = 0
            if pv > 0:
                entry["pack_version"] = pv
        if entry["order"] is None:
            del entry["order"]
        items.append(entry)

    _library_write_atomic(cat_path, {"version": 1, "items": items})


def _library_update_item(lib: Path, file: str, mutator) -> dict | None:
    """Apply mutator(entry_dict) to the library.json item matching
    `file`, persist, and return the updated entry. Returns None if no
    such entry exists. Used by the pin/reorder endpoints — they touch
    user-state fields but not the directory contents, so a full
    catalogue rebuild isn't needed."""
    with _LIBRARY_LOCK:
        cat_path = lib / "library.json"
        if not cat_path.exists():
            return None
        try:
            cat = json.loads(cat_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        items = cat.get("items", [])
        target = None
        for it in items:
            if isinstance(it, dict) and it.get("file") == file:
                target = it
                break
        if target is None:
            return None
        mutator(target)
        cat["items"] = items
        _library_write_atomic(cat_path, cat)
        return target


# v2.3.0-beta: pack discovery + install. Pre-v2.0.1 had an in-app
# pack browser; v2.0.1 ripped it out because the auto-download path
# (unsigned bridge.exe in %LOCALAPPDATA% writing fresh bytes to the
# library folder + fetching from raw.githubusercontent.com) tripped
# Defender's ML loader heuristics. v2.3.0-beta re-introduces the
# feature with the v2.2.x mitigations in place:
#   • Bridge.exe lives in Program Files (admin-only ACL → less
#     persistence-pattern-shaped to Defender).
#   • Pack ZIPs are explicit user-triggered downloads, not silent.
#   • Every ZIP entry must be a known image extension; .exe / .dll /
#     .bat / .ps1 / anything-not-an-image is refused mid-stream so
#     the extracted footprint is provably "image data only", which
#     is much harder for the ML model to classify as loader-shaped.
#   • SHA-256 of the downloaded ZIP is checked against the digest
#     in the discovery manifest (which the bridge fetches from the
#     project's GitHub Pages site — same host as the rendered docs,
#     low-suspicion traffic compared to raw.githubusercontent.com).
PACKS_MANIFEST_URL = "https://delido.github.io/signalrgb-wallpaper/library-packs.json"
PACKS_ALLOWED_ENTRY_EXTS = {".webp", ".png", ".jpg", ".jpeg",
                            ".gif", ".bmp", ".avif"}
PACKS_MAX_ZIP_BYTES = 200 * 1024 * 1024  # 200 MB ceiling per pack ZIP


def _packs_fetch_manifest() -> str:
    """Fetch the discovery manifest from GitHub Pages, return the raw
    bytes (caller parses)."""
    req = urllib.request.Request(
        PACKS_MANIFEST_URL,
        headers={"User-Agent": f"SignalRGBWallpaper-Packs/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read(2 * 1024 * 1024).decode("utf-8")


def _packs_installed_state(lib: Path) -> dict[str, int]:
    """Walk library.json and collapse it to {pack_id: max_version}.
    `pack` and `pack_version` fields are written by _packs_install
    when a pack is unpacked; entries the user added by hand carry no
    pack metadata."""
    cat_path = lib / "library.json"
    if not cat_path.exists():
        return {}
    try:
        with _LIBRARY_LOCK:
            cat = json.loads(cat_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, int] = {}
    for it in cat.get("items", []):
        if not isinstance(it, dict):
            continue
        pk = it.get("pack")
        if not isinstance(pk, str) or not pk:
            continue
        try:
            v = int(it.get("pack_version", 0))
        except Exception:
            v = 0
        if v > out.get(pk, 0):
            out[pk] = v
    return out


def _packs_install(pack_id: str, url: str, expected_sha256: str,
                   expected_size: int, pack_version: int) -> dict:
    """Download pack ZIP → SHA-256 verify → image-only extract → bump
    library.json. Runs in the executor; raises on any failure (the
    /packs/install endpoint catches and returns 400). Returns a small
    summary dict for the response."""
    if expected_size and expected_size > PACKS_MAX_ZIP_BYTES:
        raise ValueError(
            f"pack too large ({expected_size} > {PACKS_MAX_ZIP_BYTES})")
    lib = library_dir()
    lib.mkdir(parents=True, exist_ok=True)
    # Download to a sibling .part file so a crashed install never
    # leaves a half-zip in place looking like the real thing.
    tmp_dir = Path(os.environ.get(
        "TEMP", str(Path.home() / "AppData" / "Local" / "Temp")))
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_zip = tmp_dir / f"signalrgb-pack-{pack_id}.zip.part"
    if tmp_zip.exists():
        try: tmp_zip.unlink()
        except OSError: pass
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"SignalRGBWallpaper-Packs/{APP_VERSION}"})
    hasher = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_zip, "wb") as fp:
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            fp.write(chunk)
            hasher.update(chunk)
            total += len(chunk)
            if total > PACKS_MAX_ZIP_BYTES:
                try: tmp_zip.unlink()
                except OSError: pass
                raise ValueError(
                    f"pack exceeded streaming size cap ({total} bytes)")
    local_sha = hasher.hexdigest()
    if local_sha != expected_sha256:
        try: tmp_zip.unlink()
        except OSError: pass
        raise ValueError(
            f"SHA-256 mismatch: expected {expected_sha256}, "
            f"got {local_sha}")
    # Defence in depth: walk the ZIP entries BEFORE extracting and
    # refuse anything that isn't an image or the manifest.json we
    # expect. Defender's classification weighs heavily on the
    # extracted-file profile; "ZIP that contained nothing but
    # images" is the safest possible shape.
    import zipfile
    extracted_files: list[str] = []
    try:
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            for info in zf.infolist():
                name = info.filename
                if "/" in name or "\\" in name or ".." in name:
                    raise ValueError(
                        f"pack entry has path components: {name!r}")
                if name == "manifest.json":
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in PACKS_ALLOWED_ENTRY_EXTS:
                    raise ValueError(
                        f"pack contains non-image entry: {name!r}")
            # All entries pass the whitelist → extract.
            with _LIBRARY_LOCK:
                for info in zf.infolist():
                    name = info.filename
                    if name == "manifest.json":
                        continue
                    dst = lib / Path(name).name
                    with zf.open(info) as src, open(dst, "wb") as out:
                        while True:
                            blk = src.read(256 * 1024)
                            if not blk:
                                break
                            out.write(blk)
                    extracted_files.append(dst.name)
                _library_rebuild_catalogue_locked(lib)
                # Stamp every freshly-extracted item with pack +
                # pack_version so future "Update available" detection
                # works. Walks library.json once, mutates in place,
                # writes atomically.
                cat_path = lib / "library.json"
                if cat_path.exists():
                    try:
                        cat = json.loads(cat_path.read_text(encoding="utf-8"))
                    except Exception:
                        cat = {"version": 1, "items": []}
                    by_name = {n: True for n in extracted_files}
                    for it in cat.get("items", []):
                        if isinstance(it, dict) and it.get("file") in by_name:
                            it["pack"] = pack_id
                            it["pack_version"] = pack_version
                    _library_write_atomic(cat_path, cat)
    finally:
        try: tmp_zip.unlink()
        except OSError: pass
    return {
        "pack_id":       pack_id,
        "pack_version":  pack_version,
        "extracted":     len(extracted_files),
        "files":         extracted_files,
    }


def _packs_uninstall(pack_id: str) -> dict:
    """Delete every library file (+ .thumb / .4k siblings) tagged
    pack == pack_id, then rebuild library.json. Items the user added
    by hand (no pack stamp) are never touched. Returns a small summary
    for the endpoint response."""
    lib = library_dir()
    with _LIBRARY_LOCK:
        cat_path = lib / "library.json"
        if not cat_path.exists():
            return {"pack_id": pack_id, "removed": 0, "files": []}
        try:
            cat = json.loads(cat_path.read_text(encoding="utf-8"))
        except Exception:
            return {"pack_id": pack_id, "removed": 0, "files": []}
        victims: list[str] = []
        for it in cat.get("items", []):
            if (isinstance(it, dict)
                    and it.get("pack") == pack_id
                    and isinstance(it.get("file"), str)):
                victims.append(it["file"])
        removed_files: list[str] = []
        for name in victims:
            stem = Path(name).stem
            for cand in (
                lib / name,
                lib / f"{stem}.thumb.png",
                lib / f"{stem}.thumb.jpg",
                lib / f"{stem}.thumb.webp",
                lib / f"{stem}.4k.png",
                lib / f"{stem}.4k.jpg",
                lib / f"{stem}.4k.webp",
            ):
                try:
                    if cand.exists() and cand.is_file():
                        cand.unlink()
                        removed_files.append(cand.name)
                except OSError:
                    pass
        _library_rebuild_catalogue_locked(lib)
    return {
        "pack_id": pack_id,
        "removed": len(victims),
        "files":   removed_files,
    }


def _library_apply_order(lib: Path, order: list[str]) -> int:
    """Assign sequential `order` indices to entries whose `file` field
    matches the given list. Entries not in the list keep their
    existing order (if any) but are pushed past the end of the new
    list. Returns the number of items that received an order."""
    with _LIBRARY_LOCK:
        cat_path = lib / "library.json"
        if not cat_path.exists():
            return 0
        try:
            cat = json.loads(cat_path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        items = cat.get("items", [])
        by_file = {it.get("file"): it for it in items if isinstance(it, dict)}
        n = 0
        for idx, file in enumerate(order):
            it = by_file.get(file)
            if it is not None:
                it["order"] = idx
                n += 1
        # Entries not in the new order: push past the end so they sort
        # last but stay reachable. Stable across multiple reorder rounds.
        tail = len(order)
        for it in items:
            if isinstance(it, dict) and it.get("file") not in order:
                it["order"] = tail
                tail += 1
        cat["items"] = items
        _library_write_atomic(cat_path, cat)
        return n


def library_dir() -> Path:
    """Curated starter-wallpaper library. The installer drops PNGs +
    library.json here; the Configurator's `Library` section browses
    them. Users can also drop their own PNGs in here by hand — the
    bridge serves anything that's whitelisted by name, and missing
    library.json just yields an empty browser. When running from
    Python source (no installer), prefer the build-time output under
    `wallpaper_bridge/library/` so dev iterations don't require a
    full install cycle."""
    user_dir = config_path().parent / "library"
    if user_dir.exists() and any(user_dir.iterdir()):
        return user_dir
    # Dev fallback: the build-time library next to the bridge source.
    dev_dir = Path(__file__).resolve().parent / "library"
    if dev_dir.exists():
        return dev_dir
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


# v2.0.1: in-bridge Wallpaper-Pack downloader removed. The
# urlopen + zipfile.extractall pattern triggered Defender's
# Wacatac.B!ml heuristic on unsigned binaries. The packs still
# exist as GitHub release assets — users download the ZIPs
# manually from the URL the Configurator surfaces and drop
# the contents into %LOCALAPPDATA%\SignalRGBWallpaper\library\.
# The bridge's rebuild picks them up on the next /library/list.



def default_config() -> dict:
    return {
        "version": CONFIG_VERSION,
        "screenCount": 1,         # plugin polls /config and announces this many controllers
        "fullscreenPause": True,  # auto-pause glow when a fullscreen app is active
        "updateCheckEnabled": True,
        "allowBetas":         False,   # include GitHub prerelease tags in update checks
        "language":           "auto",  # "auto" | "en" | "de" — UI language
        # v2.3.1: tracks which APP_VERSION the user has already seen
        # release-notes for. After an auto-update, the Configurator
        # compares APP_VERSION against this and pops the "What's new"
        # modal once when they don't match, then writes the current
        # APP_VERSION back here. Empty default → modal fires on
        # first launch after upgrading (or on a fresh install).
        "lastSeenAppVersion": "",
        # Global Ctrl+Shift+1..4 → apply preset slot 1..4 on every active
        # screen. Disabled by default so we don't grab shortcuts the user
        # might already have wired up; tray menu flips it on.
        "presetHotkeysEnabled": False,
        # Per-app / per-game profile rules. ProfileWatcher polls
        # GetForegroundWindow every 1 s; matching rules swap the
        # target screen's preset and revert when the foreground
        # changes away. List of dicts (see ProfileWatcher).
        "profiles": [],
        # v1.4.0-beta: OpenRGB output channel. When enabled, the bridge
        # connects to OpenRGB's network SDK (default 127.0.0.1:6742)
        # and pushes the source-screen's averaged glow colour to every
        # enumerated OpenRGB device at 30 Hz. Disabled by default so
        # users who don't run OpenRGB pay nothing.
        # v1.6.2-beta: OpenRGB-SDK *server* — the inverse of the
        # `openrgbOutput` channel above. When enabled, the bridge
        # listens on `port` and exposes one virtual matrix device per
        # screen to any OpenRGB GUI / SDK client that connects. The
        # client can apply OpenRGB's built-in effects (Rainbow Wave,
        # Breathing, Audio Visualizer, …) and the resulting LED writes
        # flow back into the wallpaper as a colour source. Off by
        # default — opt-in via the Configurator's Integrations tab.
        # Port 6743 sidesteps the inevitable conflict with a running
        # OpenRGB GUI server on 6742; users who pick a different port
        # can override here.
        "openrgbSdkServer": {
            "enabled":  False,
            # v1.6.4-beta: default to loopback. Earlier "0.0.0.0"
            # default exposed the SDK server to the whole LAN — anyone
            # on the same network could enumerate + drive the
            # wallpaper. OpenRGB itself ships with the 127.0.0.1
            # default for the same reason. Users on LAN-aware setups
            # (driving from another machine) can flip this back to
            # 0.0.0.0 or a specific NIC address explicitly.
            "host":     "127.0.0.1",
            "port":     6743,
            # Grid dimensions per screen for the virtual device's
            # matrix_map. Defaults to a reasonable 32×16 (matches the
            # SignalRGB plugin's typical grid resolution). Per-screen
            # override keyed by screen index. The bridge wires the
            # matrix's row-major LED indices to the wallpaper's grid
            # zones on update.
            "matrix":   {str(n): [32, 16] for n in range(N_SCREENS)},
        },
        "openrgbOutput": {
            "enabled":      False,
            "host":         "127.0.0.1",
            "port":         6742,
            "sourceScreen": 0,
            # v1.5.0-beta hotfix6 / spatial-mapping: per-device
            # normalised (x, y) position on the source-screen's
            # colour grid. Default is the centre (0.5, 0.5), which
            # matches the v1.4 "averaged colour" behaviour on
            # uniform effects. User drags each device's marker on
            # a live-preview canvas in the Configurator to tell
            # the bridge where in the wallpaper to sample the
            # device's colour from. Keyed by stringified OpenRGB
            # device id (the index assigned by the SDK enum).
            "deviceMapping": {},
        },
        # v1.5.0-beta: per-screen colour-source picker. Default keeps
        # every screen on the historical SignalRGB UDP path so existing
        # installs keep working unchanged. Other recognised types:
        #   "openrgb"  → poll an OpenRGB device's current LEDs at 30 Hz
        #   "sacn"     → subscribe to an E1.31 multicast universe
        # The SourceManager validates incoming frames against this map;
        # frames from the wrong source for a given screen are dropped.
        "sources": {
            str(n): {"type": "signalrgb"} for n in range(N_SCREENS)
        },
        # v1.5.0-beta: sACN/E1.31 outbound emitter — parallel to the
        # OpenRGB-output channel above, hooks the broadcaster's frame
        # tap. When enabled, broadcasts the per-screen averaged glow
        # to one configured universe per screen on the standard E1.31
        # multicast group (239.255.X.Y, port 5568). Receivers: xLights,
        # QLC+, Hyperion, any hardware ArtNet/sACN node, etc.
        "sacnOutput": {
            "enabled":   False,
            # "multicast" (default, conformant) or "unicast" (point at
            # a specific receiver — useful when traversing a router
            # that drops 239.255/16 traffic).
            "destination": "multicast",
            "unicastHost": "",
            "priority":  100,
            # Per-screen universe assignment. screen index → universe.
            # Defaults: screen 0 → universe 1, screen 1 → 2, …
            "universes": {str(n): n + 1 for n in range(N_SCREENS)},
        },
        # v1.5.0-beta: REST API bearer token. Auto-generated on first
        # run; shown + regenerable in the Configurator's System card.
        # Bypassed for loopback requests so the existing Configurator
        # / wallpaper page keep working without changes — gating only
        # kicks in when a request arrives over a non-127.0.0.1 socket
        # (future-proofing for the LAN-binding opt-in).
        "apiToken": secrets.token_urlsafe(32),
        # v1.5.0-beta: HA / MQTT bridge config. Disabled by default;
        # publishes per-screen state to a configurable topic prefix
        # and subscribes to .../set topics for control. See the
        # MqttBridge class for the topic layout.
        "mqttBridge": {
            "enabled":     False,
            "host":        "localhost",
            "port":        1883,
            "username":    "",
            "password":    "",
            "clientId":    "signalrgb-wallpaper",
            "topicPrefix": "signalrgb-wallpaper",
            # HA MQTT Discovery: bridge publishes `<discoveryPrefix>
            # /<component>/<bridge>/<entity>/config` payloads on
            # connect so Home Assistant auto-creates entities under
            # one device card. Default "homeassistant" matches
            # HA's out-of-the-box discovery topic. Set blank to
            # suppress discovery entirely (raw topics still publish).
            "discoveryPrefix": "homeassistant",
        },
        "screens": {str(n): dict(DEFAULT_SCREEN_SETTINGS) for n in range(N_SCREENS)},
    }


# ============================================================================
# Localisation (DE / EN)
# ============================================================================
#
# Single-file string table. `tr(key)` returns the localised string for the
# active language; format parameters get spliced in via str.format. Falls
# back to English then to the key itself, so an untranslated string never
# crashes — it just shows up as the dotted-key, which makes missing entries
# obvious during dev.
#
# Coverage: tray menu, About dialog, the Configurator's main labels, and
# (since v0.7.4-beta) the Builder window — the Builder has its own
# in-page TRANSLATIONS map and fetches the active language from /config.
# ----------------------------------------------------------------------------

TRANSLATIONS = {
    # ── Tray menu ────────────────────────────────────────────────────
    "tray.configurator":        {"en": "Configurator…",           "de": "Konfigurator…"},
    "tray.builder":             {"en": "Build Wallpaper…",        "de": "Wallpaper bauen…"},
    "tray.help":                {"en": "Help…",                   "de": "Hilfe…"},
    "tray.export_diagnostics":  {"en": "Export diagnostics bundle…",
                                 "de": "Diagnose-Paket exportieren…"},
    "tray.open_library_folder": {"en": "Open library folder…",
                                 "de": "Bibliotheksordner öffnen…"},
    "diagnostics.done":         {"en": "Diagnostics bundle saved to {path}",
                                 "de": "Diagnose-Paket gespeichert: {path}"},
    "diagnostics.failed":       {"en": "Diagnostics export failed: {msg}",
                                 "de": "Diagnose-Export fehlgeschlagen: {msg}"},
    "tray.status":              {"en": "System status…",          "de": "Systemstatus…"},
    # ── System Status dialog ────────────────────────────────────────
    "status.title":             {"en": "System status",
                                 "de": "Systemstatus"},
    "status.subtitle":          {"en": "Quick check of every signal that has to be green for the wallpaper to actually light up.",
                                 "de": "Kurzcheck aller Signale, die grün sein müssen, damit das Wallpaper leuchtet."},
    "status.plugin":            {"en": "SignalRGB plugin file installed",
                                 "de": "SignalRGB-Plugin-Datei installiert"},
    "status.signalrgb":         {"en": "SignalRGB.exe running",
                                 "de": "SignalRGB.exe läuft"},
    "status.bridge":            {"en": "Bridge reachable on {host}:{port}",
                                 "de": "Bridge erreichbar auf {host}:{port}"},
    "status.pages":             {"en": "Wallpaper pages connected: {n}",
                                 "de": "Verbundene Wallpaper-Seiten: {n}"},
    "status.lhm":               {"en": "LibreHardwareMonitor reachable ({n} sensors)",
                                 "de": "LibreHardwareMonitor erreichbar ({n} Sensoren)"},
    "status.btn.open_plugins":  {"en": "Open plugins folder",
                                 "de": "Plugin-Ordner öffnen"},
    "status.btn.get_signalrgb": {"en": "Download SignalRGB",
                                 "de": "SignalRGB herunterladen"},
    "status.btn.get_lhm":       {"en": "Download LHM",
                                 "de": "LHM herunterladen"},
    "status.btn.help":          {"en": "Open Help",
                                 "de": "Hilfe öffnen"},
    "status.btn.refresh":       {"en": "Refresh",
                                 "de": "Aktualisieren"},
    "tray.pause":               {"en": "Pause glow + animations",
                                 "de": "Glow + Animationen pausieren"},
    "tray.lock_all":            {"en": "🔓 Lock widgets (all screens)",
                                 "de": "🔓 Widgets sperren (alle Bildschirme)"},
    "tray.unlock_all":          {"en": "🔒 Unlock widgets (all screens)",
                                 "de": "🔒 Widgets entsperren (alle Bildschirme)"},
    "tray.advanced":            {"en": "Advanced",                "de": "Erweitert"},
    "tray.legacy_settings":     {"en": "Legacy Settings dialog…",
                                 "de": "Klassischer Settings-Dialog…"},
    "tray.quick_add_widget":    {"en": "Quick add widget",        "de": "Widget schnell hinzufügen"},
    "tray.quick_effects":       {"en": "Quick effects",           "de": "Effekte (Schnellzugriff)"},
    "tray.reload_config":       {"en": "Reload config",           "de": "Konfig neu laden"},
    "tray.reimport_bundles":    {"en": "Re-import wallpaper bundles…",
                                 "de": "Wallpaper-Bundles neu importieren…"},
    "tray.reimport_bundles.toast.ok": {
        "en": "Re-import done. Wallpaper hosts will pick up the new bundle on next apply.",
        "de": "Re-Import fertig. Wallpaper-Hosts laden das neue Bundle beim nächsten Apply."},
    "tray.reimport_bundles.toast.partial": {
        "en": "Re-import partial — see %TEMP%\\signalrgb-reimport.log for details.",
        "de": "Re-Import teilweise — Details in %TEMP%\\signalrgb-reimport.log."},
    "tray.reimport_bundles.toast.fail": {
        "en": "Re-import failed — see %TEMP%\\signalrgb-reimport.log for details.",
        "de": "Re-Import fehlgeschlagen — Details in %TEMP%\\signalrgb-reimport.log."},
    # v2.4.3: the Workshop copy is Steam-managed and can't be touched
    # from here. Saying "done" would leave subscribers believing they
    # already have the update — which is how the v2.4.2 fix failed to
    # reach the user who reported the bug it fixed.
    "tray.reimport_bundles.toast.workshop": {
        "en": "You're subscribed on the Steam Workshop — Steam delivers the "
              "update itself (restart Steam to force a check), then re-apply "
              "the wallpaper in Wallpaper Engine.",
        "de": "Du bist im Steam-Workshop abonniert — Steam liefert das Update "
              "selbst (Steam neu starten erzwingt eine Prüfung). Danach das "
              "Wallpaper in Wallpaper Engine erneut zuweisen."},
    "tray.reload_wallpapers":   {"en": "Reload wallpaper pages",
                                 "de": "Wallpaper-Seiten neu laden"},
    "tray.updates":             {"en": "Updates",                 "de": "Updates"},
    "tray.about":               {"en": "About…",                  "de": "Über…"},
    "tray.quit":                {"en": "Quit",                    "de": "Beenden"},
    "tray.screen_n":            {"en": "Screen {n}",              "de": "Bildschirm {n}"},
    # ── Updates submenu ─────────────────────────────────────────────
    "updates.check_now":        {"en": "Check for updates now",   "de": "Jetzt nach Updates suchen"},
    "updates.enable":           {"en": "Enable update checks",    "de": "Update-Suche aktivieren"},
    "updates.allow_beta":       {"en": "Allow beta versions",     "de": "Beta-Versionen erlauben"},
    "updates.latest":           {"en": "Latest: {tag} — open release page",
                                 "de": "Verfügbar: {tag} — Release-Seite öffnen"},
    "updates.up_to_date":       {"en": "Up to date — last checked {ago}",
                                 "de": "Aktuell — zuletzt geprüft {ago}"},
    "updates.not_checked":      {"en": "Not yet checked",         "de": "Noch nicht geprüft"},
    "updates.last_failed":      {"en": "Last check failed: {err}",
                                 "de": "Letzte Prüfung fehlgeschlagen: {err}"},
    "updates.install_now":      {"en": "⬇  Download + install {tag}",
                                 "de": "⬇  {tag} herunterladen + installieren"},
    "updates.installing_title": {"en": "Installing {tag}",
                                 "de": "Installiere {tag}"},
    "updates.installing_start": {"en": "Starting download…",
                                 "de": "Download startet…"},
    "updates.installing_progress": {"en": "Downloading… {pct}%  ({done_mb} / {total_mb} MB)",
                                 "de": "Lade herunter… {pct}%  ({done_mb} / {total_mb} MB)"},
    "updates.installing_done":  {"en": "Installer launched — bridge will restart automatically.",
                                 "de": "Installer gestartet — Bridge wird automatisch neugestartet."},
    "updates.installing_failed": {"en": "Update failed: {msg}",
                                 "de": "Update fehlgeschlagen: {msg}"},
    "updates.installing_hint":  {"en": "The bridge will exit when the installer takes over. Don't close this window manually.",
                                 "de": "Die Bridge wird sich beenden, sobald der Installer übernimmt. Bitte dieses Fenster nicht manuell schließen."},
    "updates.available_top":    {"en": "⬆  Update available: {tag} — open release page",
                                 "de": "⬆  Update verfügbar: {tag} — Release-Seite öffnen"},
    "updates.installed":        {"en": "Installed: v{ver}",       "de": "Installiert: v{ver}"},
    "updates.balloon_title":    {"en": "SignalRGB Wallpaper update",
                                 "de": "SignalRGB-Wallpaper-Update"},
    "updates.balloon_msg":      {"en": "Version {tag} is available. Open the tray menu to view the release page.",
                                 "de": "Version {tag} ist verfügbar. Öffne das Tray-Menü um die Release-Seite zu öffnen."},
    # ── Effects submenu ─────────────────────────────────────────────
    "effects.ambient_label":    {"en": "Ambient effect",          "de": "Umgebungseffekt"},
    "effects.pixelfx_label":    {"en": "Pixelfx (cursor)",        "de": "Pixelfx (Cursor)"},
    "effects.tint_with_glow":   {"en": "Tint particles with glow colour",
                                 "de": "Partikel mit Glow-Farbe einfärben"},
    "ambient.off":              {"en": "Off",                     "de": "Aus"},
    "ambient.snow":             {"en": "Snow",                    "de": "Schnee"},
    "ambient.rain":             {"en": "Rain",                    "de": "Regen"},
    "ambient.sparks":           {"en": "Sparks",                  "de": "Funken"},
    "ambient.aurora":           {"en": "Aurora",                  "de": "Aurora"},
    "pixelfx.off":              {"en": "Off",                     "de": "Aus"},
    "pixelfx.trail":            {"en": "Mouse trail",             "de": "Mausspur"},
    "pixelfx.glow":             {"en": "Hover glow",              "de": "Cursor-Glow"},
    "pixelfx.ripple":           {"en": "Click ripple (needs Lively interaction)",
                                 "de": "Klick-Welle (benötigt Lively-Interaktion)"},
    "pixelfx.water":            {"en": "Water ripple (needs Lively interaction)",
                                 "de": "Wasserwelle (benötigt Lively-Interaktion)"},
    # ── Widgets submenu ─────────────────────────────────────────────
    "widgets.edit_toggle":      {"en": "Edit widgets on this screen  ({state})",
                                 "de": "Widgets bearbeiten  ({state})"},
    "widgets.state.locked":     {"en": "locked",                  "de": "gesperrt"},
    "widgets.state.edit":       {"en": "EDIT MODE",               "de": "BEARBEITUNGSMODUS"},
    "widgets.placed_count":     {"en": "Currently placed: {n}",   "de": "Aktuell platziert: {n}"},
    "widgets.add_x":            {"en": "Add {label}",             "de": "{label} hinzufügen"},
    # ── About dialog ────────────────────────────────────────────────
    "about.title":              {"en": "About {app}",             "de": "Über {app}"},
    "about.version":            {"en": "Version {ver}",           "de": "Version {ver}"},
    "about.github_handle":      {"en": "@{user} on GitHub",       "de": "@{user} auf GitHub"},
    "about.copyright":          {"en": "© 2026 {author} · MIT Licensed",
                                 "de": "© 2026 {author} · MIT-Lizenz"},
    "about.tagline":            {"en": "Live SignalRGB-driven glow behind your wallpaper, with placeable widgets, ambient effects and a one-shot installer.",
                                 "de": "Live SignalRGB-gesteuertes Glow hinter deinem Wallpaper, mit platzierbaren Widgets, Umgebungseffekten und einem Ein-Klick-Installer."},
    "about.btn.github":         {"en": "Project on GitHub",       "de": "Projekt auf GitHub"},
    "about.btn.license":        {"en": "MIT License",             "de": "MIT-Lizenz"},
    "about.btn.credits":        {"en": "Open-source credits",     "de": "Open-Source-Credits"},
    "about.btn.donate":         {"en": "☕  Buy me a coffee (PayPal)",
                                 "de": "☕  Spendier mir einen Kaffee (PayPal)"},
    "about.btn.close":          {"en": "Close",                   "de": "Schließen"},
    # ── Relative-time helpers used by tray ──────────────────────────
    "ago.s":                    {"en": "{n}s ago",                "de": "vor {n}s"},
    "ago.m":                    {"en": "{n}m ago",                "de": "vor {n}min"},
    "ago.h":                    {"en": "{n}h ago",                "de": "vor {n}h"},
}

_CURRENT_LANG = "en"


def _detect_default_lang() -> str:
    """Return 'de' if the system locale starts with German, else 'en'."""
    try:
        loc = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""
        if loc.lower().startswith("de"):
            return "de"
    except Exception:
        pass
    env = (os.environ.get("LANG", "") or os.environ.get("LANGUAGE", "")).lower()
    if env.startswith("de"):
        return "de"
    return "en"


def init_language(config: dict) -> None:
    """Resolve the active language from config + system locale and stash it."""
    global _CURRENT_LANG
    pref = (config.get("language") or "auto").lower()
    if pref in ("en", "de"):
        _CURRENT_LANG = pref
    else:
        _CURRENT_LANG = _detect_default_lang()
    print(f"[i18n] language = {_CURRENT_LANG}")


def tr(key: str, **kwargs) -> str:
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    text = entry.get(_CURRENT_LANG) or entry.get("en") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def _migrate_config(cfg: dict) -> dict:
    """Apply structural migrations to a loaded config.json before the
    generic `setdefault` backfill runs in load_config(). One branch per
    `from_version → to_version`; each branch should be idempotent so
    re-running on an already-migrated config is a no-op.

    v1.2.13 — initial scaffold. Empty for now (every shape change so
    far has been additive enough that the `setdefault` backfill +
    DEFAULT_SCREEN_SETTINGS merge in load_config() covered it). Add a
    branch the next time a key gets renamed or its inner shape
    changes — bump CONFIG_VERSION at the same time."""
    try:
        cur = int(cfg.get("version") or 0)
    except (TypeError, ValueError):
        cur = 0
    if cur >= CONFIG_VERSION:
        return cfg
    # Stamp the running version so a subsequent save_config records
    # the migrated state. Branches below would update `cur` as they
    # apply each step.
    cfg["version"] = CONFIG_VERSION
    return cfg


def load_config() -> dict:
    p = config_path()
    if not p.exists():
        cfg = default_config()
        save_config(cfg)
        return cfg
    try:
        with p.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"[config] load failed ({e}); resetting to defaults")
        cfg = default_config()
        save_config(cfg)
        return cfg
    # v1.2.13: run targeted migrations BEFORE the generic setdefault
    # backfill below. Backfill assumes shape; migrations fix shape.
    cfg = _migrate_config(cfg)
    # Migrate / backfill so older configs gain new fields without erroring.
    cfg.setdefault("version", CONFIG_VERSION)
    cfg.setdefault("screenCount", 1)
    try:
        cfg["screenCount"] = max(1, min(N_SCREENS, int(cfg["screenCount"])))
    except (TypeError, ValueError):
        cfg["screenCount"] = 1
    cfg.setdefault("fullscreenPause", True)
    cfg["fullscreenPause"] = bool(cfg.get("fullscreenPause", True))
    cfg.setdefault("updateCheckEnabled", True)
    cfg["updateCheckEnabled"] = bool(cfg.get("updateCheckEnabled", True))
    cfg.setdefault("allowBetas", False)
    cfg["allowBetas"] = bool(cfg.get("allowBetas", False))
    cfg.setdefault("language", "auto")
    if cfg.get("language") not in ("auto", "en", "de"):
        cfg["language"] = "auto"
    # v1.4.0-beta: OpenRGB output config block. Backfill the whole
    # sub-dict for pre-v1.4 configs; setdefault each leaf inside it so
    # a partial override (user manually edited just `enabled`) keeps
    # the other defaults.
    cfg.setdefault("openrgbOutput", {})
    if not isinstance(cfg.get("openrgbOutput"), dict):
        cfg["openrgbOutput"] = {}
    cfg["openrgbOutput"].setdefault("enabled", False)
    cfg["openrgbOutput"].setdefault("host", "127.0.0.1")
    cfg["openrgbOutput"].setdefault("port", 6742)
    cfg["openrgbOutput"].setdefault("sourceScreen", 0)
    # v1.5.0-beta spatial-mapping backfill. Shape: {id_str: {x, y}}.
    cfg["openrgbOutput"].setdefault("deviceMapping", {})
    if not isinstance(cfg["openrgbOutput"].get("deviceMapping"), dict):
        cfg["openrgbOutput"]["deviceMapping"] = {}
    # v1.6.2-beta: OpenRGB-SDK server block. Backfill for pre-v1.6.2
    # configs. Sources list adds "openrgb-sdk" as a valid `type` in
    # the per-screen picker so the wallpaper can be told to render
    # SDK-server-driven colours.
    cfg.setdefault("openrgbSdkServer", {})
    if not isinstance(cfg.get("openrgbSdkServer"), dict):
        cfg["openrgbSdkServer"] = {}
    cfg["openrgbSdkServer"].setdefault("enabled", False)
    # v1.6.4-beta: loopback default (was 0.0.0.0 = LAN-exposed).
    cfg["openrgbSdkServer"].setdefault("host", "127.0.0.1")
    cfg["openrgbSdkServer"].setdefault("port", 6743)
    cfg["openrgbSdkServer"].setdefault("matrix", {})
    if not isinstance(cfg["openrgbSdkServer"].get("matrix"), dict):
        cfg["openrgbSdkServer"]["matrix"] = {}
    for n in range(N_SCREENS):
        m = cfg["openrgbSdkServer"]["matrix"].setdefault(str(n), [32, 16])
        # Tolerate single-int (treated as square) or list/tuple.
        if isinstance(m, int):
            cfg["openrgbSdkServer"]["matrix"][str(n)] = [m, m]
        elif (not isinstance(m, (list, tuple)) or len(m) != 2
              or not all(isinstance(v, int) and v > 0 for v in m)):
            cfg["openrgbSdkServer"]["matrix"][str(n)] = [32, 16]
    # v1.5.0-beta: per-screen source picker. Default every screen to
    # "signalrgb" so existing installs see no behavioural change.
    cfg.setdefault("sources", {})
    if not isinstance(cfg.get("sources"), dict):
        cfg["sources"] = {}
    for n in range(N_SCREENS):
        src = cfg["sources"].setdefault(str(n), {})
        if not isinstance(src, dict):
            cfg["sources"][str(n)] = src = {}
        src.setdefault("type", "signalrgb")
        if src["type"] not in ("signalrgb", "openrgb", "sacn", "openrgb-sdk"):
            src["type"] = "signalrgb"
        # Per-type defaults — kept in the same dict so the Configurator
        # can read every field whether the source is currently active
        # or not (UI keeps last-used values when switching).
        if src["type"] == "openrgb":
            src.setdefault("host", "127.0.0.1")
            src.setdefault("port", 6742)
            src.setdefault("deviceIndex", 0)
        elif src["type"] == "sacn":
            src.setdefault("universe", n + 1)
    # v1.5.0-beta: sACN output block. Same shape-tolerant backfill as
    # openrgbOutput above.
    cfg.setdefault("sacnOutput", {})
    if not isinstance(cfg.get("sacnOutput"), dict):
        cfg["sacnOutput"] = {}
    cfg["sacnOutput"].setdefault("enabled", False)
    cfg["sacnOutput"].setdefault("destination", "multicast")
    cfg["sacnOutput"].setdefault("unicastHost", "")
    cfg["sacnOutput"].setdefault("priority", 100)
    cfg["sacnOutput"].setdefault("universes", {})
    if not isinstance(cfg["sacnOutput"]["universes"], dict):
        cfg["sacnOutput"]["universes"] = {}
    for n in range(N_SCREENS):
        cfg["sacnOutput"]["universes"].setdefault(str(n), n + 1)
    # v1.5.0-beta: REST API token backfill. Generated lazily so
    # pre-v1.5 configs get a fresh token on first migration; existing
    # tokens (string, non-empty) are preserved across upgrades.
    tok = cfg.get("apiToken")
    if not (isinstance(tok, str) and len(tok) >= 16):
        cfg["apiToken"] = secrets.token_urlsafe(32)
    # v1.5.0-beta: MQTT bridge backfill.
    cfg.setdefault("mqttBridge", {})
    if not isinstance(cfg.get("mqttBridge"), dict):
        cfg["mqttBridge"] = {}
    cfg["mqttBridge"].setdefault("enabled", False)
    cfg["mqttBridge"].setdefault("host", "localhost")
    cfg["mqttBridge"].setdefault("port", 1883)
    cfg["mqttBridge"].setdefault("username", "")
    cfg["mqttBridge"].setdefault("password", "")
    cfg["mqttBridge"].setdefault("clientId", "signalrgb-wallpaper")
    cfg["mqttBridge"].setdefault("topicPrefix", "signalrgb-wallpaper")
    cfg["mqttBridge"].setdefault("discoveryPrefix", "homeassistant")
    cfg.setdefault("screens", {})
    for n in range(N_SCREENS):
        s = cfg["screens"].setdefault(str(n), {})
        for k, v in DEFAULT_SCREEN_SETTINGS.items():
            s.setdefault(k, v)
        # Pad / truncate the presets list to PRESET_SLOTS so a config
        # written by an older build (with no presets) gets the right
        # number of empty slots, and one from a future build with more
        # slots gets the surplus dropped (defensive, not critical).
        if not isinstance(s.get("presets"), list):
            s["presets"] = [None] * PRESET_SLOTS
        elif len(s["presets"]) < PRESET_SLOTS:
            s["presets"] = list(s["presets"]) + [None] * (PRESET_SLOTS - len(s["presets"]))
        elif len(s["presets"]) > PRESET_SLOTS:
            s["presets"] = list(s["presets"])[:PRESET_SLOTS]
        # v1.2.13: drop stale bgImage references whose file no longer
        # exists on disk. Pre-v1.2.13 a manual cleanup of the screens
        # folder left bgImage pointing into the void; the wallpaper
        # page would silently fail to load anything and the
        # Configurator's library overview rendered a broken thumbnail.
        bg = s.get("bgImage")
        if isinstance(bg, str) and bg:
            # Only check absolute paths — http(s)/data URLs pass
            # through. Network reachability isn't our problem.
            looks_local = not bg.startswith(("http://", "https://", "data:"))
            if looks_local:
                bg_path = bg.replace("file://", "").lstrip("/")
                # bridge stores paths the wallpaper-page-side proxy
                # consumes; treat absolute paths or screens-dir
                # relatives as resolvable here.
                try:
                    if not Path(bg).exists() and not (screens_dir() / bg_path).exists():
                        print(f"[config] dropping stale bgImage for screen {n}: {bg}")
                        s["bgImage"] = ""
                except Exception:
                    pass
    return cfg


def save_config(cfg: dict) -> None:
    p = config_path()
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    tmp.replace(p)


# ============================================================================
# WebSocket helpers
# ============================================================================

def parse_http_headers(raw: bytes) -> dict:
    headers = {}
    for line in raw.split(b"\r\n")[1:]:
        if b":" in line:
            k, _, v = line.partition(b":")
            headers[k.strip().lower()] = v.strip()
    return headers


def _acao(headers=None) -> str:
    """Resolve the Access-Control-Allow-Origin header value for an
    outgoing response. v1.2.13 hardening: the previous `*` default
    let any random web page the user visited probe / mutate the
    bridge in the background. We now only echo back an Origin that
    appears in `_ALLOWED_HTTP_ORIGINS`; the bridge's own loopback
    URL is the safe default when the caller has no headers in hand
    (background pushes, internally-generated responses)."""
    if headers is not None:
        try:
            allowed = _cors_origin_value(headers.get(b"origin"))
            if allowed:
                return allowed
        except Exception:
            pass
    return f"http://{WS_HOST}:{WS_PORT}"


def make_handshake(request: bytes) -> bytes | None:
    headers = parse_http_headers(request)
    if headers.get(b"upgrade", b"").lower() != b"websocket":
        return None
    key = headers.get(b"sec-websocket-key")
    if not key:
        return None
    accept = base64.b64encode(hashlib.sha1(key + WS_GUID).digest()).decode()
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    ).encode()


def _encode_frame(opcode: int, payload: bytes) -> bytes:
    header = bytearray([0x80 | (opcode & 0x0f)])  # FIN=1 + opcode
    n = len(payload)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += struct.pack(">H", n)
    else:
        header.append(127)
        header += struct.pack(">Q", n)
    return bytes(header) + payload


def encode_binary_frame(payload: bytes) -> bytes:
    return _encode_frame(0x2, payload)


def encode_text_frame(text: str) -> bytes:
    return _encode_frame(0x1, text.encode("utf-8"))


def encode_ping_frame(payload: bytes = b"") -> bytes:
    """v2.4.1: server→client WS ping (opcode 0x9). Used by the
    keepalive task to detect half-open sockets after a Windows
    sleep/resume — see WsBroadcaster._keepalive_loop()."""
    return _encode_frame(0x9, payload)


# v2.4.1: sentinel returned by read_client_text_frame() when the frame
# was a pong. The read loop treats it as "client is alive" and refreshes
# the last-seen timestamp. Distinct from "" (ignored frame) so an
# ordinary binary/fragmented frame doesn't count as liveness proof.
PONG_SENTINEL = "\x00__pong__"


async def read_client_text_frame(reader) -> str | None:
    """Read one masked client→server WS frame; return its decoded text body
    if it's a text frame, None on close/control/error, PONG_SENTINEL for a
    pong. Skips binary frames silently — the wallpaper page only ever sends
    JSON text messages back to the bridge."""
    try:
        header = await reader.readexactly(2)
    except (asyncio.IncompleteReadError, ConnectionError):
        return None
    b1, b2 = header[0], header[1]
    fin = (b1 & 0x80) != 0
    opcode = b1 & 0x0f
    masked = (b2 & 0x80) != 0
    n = b2 & 0x7f
    if n == 126:
        n = struct.unpack(">H", await reader.readexactly(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", await reader.readexactly(8))[0]
    # v1.2.6: cap the frame size. The wallpaper page only ever sends
    # small single-frame JSON blobs (largest is a Quick-Look apply,
    # a few KB). A header claiming a multi-GB payload — from a bug or
    # a malicious local client — would otherwise make readexactly(n)
    # try to buffer that much and OOM the bridge. 4 MiB is generous
    # headroom (a 4-monitor widgets array can't approach it) and far
    # below anything dangerous.
    MAX_TEXT_FRAME = 4 * 1024 * 1024
    if n > MAX_TEXT_FRAME:
        print(f"[ws] rejecting oversized client frame: {n} bytes")
        return None
    # Browser → server frames MUST be masked per RFC 6455. Reject anything
    # else (defensive — should never happen with real browser clients).
    mask = await reader.readexactly(4) if masked else b"\x00\x00\x00\x00"
    payload = await reader.readexactly(n) if n else b""
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if opcode == 0x8:    # close
        return None
    if opcode == 0x9:    # ping from the client — RFC 6455 requires a pong
        # v2.4.1: we used to drop these on the floor. Browsers don't
        # normally ping us, but a client that does would otherwise time
        # us out. The caller owns the writer, so signal via sentinel and
        # let it send the pong (readers here have no writer handle).
        return PONG_SENTINEL
    if opcode == 0xA:    # pong — reply to OUR keepalive ping
        return PONG_SENTINEL
    if opcode != 0x1:    # not text → caller skips
        return ""
    if not fin:
        # Wallpaper-page messages are tiny single-frame JSON blobs. Anything
        # fragmented gets dropped rather than reassembled.
        return ""
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return ""


# ============================================================================
# HTTP image proxy
# ============================================================================

def http_error(writer, code: int, message: str, *, request_headers=None):
    body = message.encode("utf-8")
    status = {400: "Bad Request", 403: "Forbidden", 404: "Not Found",
              415: "Unsupported Media Type", 500: "Server Error"}.get(code, "Error")
    head = (
        f"HTTP/1.1 {code} {status}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Access-Control-Allow-Origin: {_acao(request_headers)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    writer.write(head + body)


async def http_serve_image(writer, query: str, range_hdr: str = "", *, request_headers=None):
    """Serve an image or video file by absolute path.

    v1.2.6 rewrite:
      • Accepts video extensions (was image-only → 415 on video bgs).
      • Honours HTTP Range requests with a 206 Partial Content
        response. Browsers REQUIRE range support to play a <video>
        element from a URL — without it Chromium/CEF often refuse to
        start playback or re-download the whole clip every loop.
      • Streams the file in 256 KiB chunks instead of read_bytes()-ing
        the whole thing into RAM (a 300 MB video bg used to spike the
        bridge's memory by 300 MB per request).
    """
    params = urllib.parse.parse_qs(query)
    raw_path = params.get("path", [""])[0]
    if not raw_path:
        return http_error(writer, 400, "missing 'path' query parameter")
    path = urllib.parse.unquote(raw_path)
    ext = os.path.splitext(path)[1].lower()
    if ext not in SERVABLE_EXTS:
        return http_error(writer, 415, f"unsupported extension: {ext or '(none)'}")
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        return http_error(writer, 404, f"file not found: {abs_path}")
    try:
        size = os.path.getsize(abs_path)
    except OSError as e:
        return http_error(writer, 403, f"cannot stat file: {e}")
    content_type = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"
    is_video = ext in VIDEO_EXTS

    # Parse a single-range "bytes=START-END" header. We don't bother
    # with multi-range (browsers asking a <video> for one range at a
    # time is the only case that matters here).
    start, end = 0, size - 1
    partial = False
    if range_hdr.lower().startswith("bytes="):
        try:
            spec = range_hdr.split("=", 1)[1].split(",", 1)[0].strip()
            lo, _, hi = spec.partition("-")
            if lo == "":
                # suffix range: bytes=-N → last N bytes
                n = int(hi)
                start = max(0, size - n)
                end = size - 1
            else:
                start = int(lo)
                end = int(hi) if hi else size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                # Unsatisfiable — RFC says 416 with Content-Range */size.
                head = (
                    f"HTTP/1.1 416 Range Not Satisfiable\r\n"
                    f"Content-Range: bytes */{size}\r\n"
                    f"Access-Control-Allow-Origin: {_acao(request_headers)}\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode()
                writer.write(head)
                return
            partial = True
        except (ValueError, IndexError):
            start, end = 0, size - 1
            partial = False

    length = end - start + 1
    # Image cache is short (background swaps want freshness); video is
    # immutable-ish per timestamped filename so it can cache longer.
    cache = "public, max-age=86400" if is_video else "max-age=10"
    status = "206 Partial Content" if partial else "200 OK"
    head_lines = [
        f"HTTP/1.1 {status}",
        f"Content-Type: {content_type}",
        f"Content-Length: {length}",
        "Accept-Ranges: bytes",
        f"Cache-Control: {cache}",
        f"Access-Control-Allow-Origin: {_acao(request_headers)}",
        "Connection: close",
    ]
    if partial:
        head_lines.insert(3, f"Content-Range: bytes {start}-{end}/{size}")
    writer.write(("\r\n".join(head_lines) + "\r\n\r\n").encode())

    # Stream the requested byte window in chunks with backpressure so a
    # large video doesn't balloon the bridge's memory.
    CHUNK = 256 * 1024
    try:
        with open(abs_path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                buf = f.read(min(CHUNK, remaining))
                if not buf:
                    break
                writer.write(buf)
                remaining -= len(buf)
                try:
                    await writer.drain()
                except Exception:
                    break
    except OSError as e:
        # Headers already sent; best we can do is stop writing.
        print(f"[image] read failed mid-stream: {e}")


def parse_query_screen(target: str) -> int:
    if "?" not in target:
        return 0
    _, _, query = target.partition("?")
    params = urllib.parse.parse_qs(query)
    try:
        n = int(params.get("screen", ["0"])[0])
    except (TypeError, ValueError):
        return 0
    if n < 0 or n > MAX_SCREEN_INDEX:
        return 0
    return n


def parse_query_role(target: str) -> str:
    """Identify what kind of client opened this WS — `wallpaper` (the
    page Lively/WE renders, default for legacy clients) or
    `configurator` (the in-browser settings UI). The Status dialog
    counts only `wallpaper` clients so the user sees actual rendered
    pages, not their own open Configurator tab."""
    if "?" not in target:
        return "wallpaper"
    _, _, query = target.partition("?")
    params = urllib.parse.parse_qs(query)
    role = (params.get("role", ["wallpaper"])[0] or "wallpaper").lower()
    return role if role in ("wallpaper", "configurator") else "wallpaper"


# ============================================================================
# Broadcaster — UDP fan-out + settings push
# ============================================================================

class Broadcaster:
    """
    Routes UDP datagrams to WS clients filtered by screen-index, and pushes
    settings updates as JSON text frames. The asyncio loop drives all I/O;
    cross-thread calls (e.g. tray->push_settings) use call_soon_threadsafe.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, get_settings, get_screen_count, update_background, get_paused, on_widget_command, get_bridge_state=None):
        self.loop = loop
        self.get_settings = get_settings        # callable(screen:int)->dict
        self.get_screen_count = get_screen_count  # callable()->int (1..N_SCREENS)
        self.update_background = update_background  # callable(screen:int, png_bytes:bytes)->bool
        self.get_paused = get_paused            # callable()->bool (fullscreen-induced pause)
        self.on_widget_command = on_widget_command  # callable(screen:int, msg:dict)->None
        # v1.2.1: callable()->dict of bridge-scoped (non-per-screen)
        # booleans the Configurator's System section reads (fullscreenPause,
        # updateCheckEnabled, allowBetas, presetHotkeysEnabled). Optional
        # so older callers don't break; defaults to an empty dict.
        self.get_bridge_state = get_bridge_state or (lambda: {})
        # The hwmon provider is wired in after construction (BridgeRuntime
        # builds the broadcaster before it builds the HwMonPoller). Stays
        # None until then; the /hwmon/sensors endpoint just reports
        # "online: false" if it's missing.
        self.hwmon_provider = None             # set externally; HwMonPoller
        # v1.2.12: similarly set externally by BridgeRuntime once the
        # UdpReceiver exists, so the /config endpoint can surface the
        # per-screen plugin send rate ("Plugin is sending at ~165 fps")
        # for the Configurator's frameRate picker.
        self.udp_provider = None
        self.clients_by_screen: dict[int, set] = {}
        self._lock = asyncio.Lock()
        # v2.2.2: per-client consecutive-skip counter for the slow-
        # client force-close logic. See _client_should_skip().
        self._client_skip_count: dict = {}
        # v2.4.1: per-client last-seen timestamp (loop clock), refreshed
        # on every inbound frame — including pongs to our keepalive ping.
        # _keepalive_loop() reaps anything that hasn't spoken within
        # CLIENT_IDLE_TIMEOUT_S. Fixes the stuck "bridge offline" card
        # after a Windows sleep/resume: the loopback socket comes back
        # half-open, writes still "succeed" into the transport buffer,
        # so without an explicit liveness probe neither side ever
        # notices the peer is gone. See issue #2.
        self._client_last_seen: dict = {}
        # v1.2.12: per-screen last-broadcast timestamp for the
        # outgoing rate cap. The interval per screen comes from the
        # screen's `frameRate` setting (20 / 30 / 60 Hz); the page
        # gates its renderFrame at the same value so the bridge
        # never wastes a WS frame the page would just drop.
        self._last_broadcast_per_screen: dict[int, float] = {}
        # v1.4.0: per-frame tap callbacks. `add_frame_tap(cb)` registers
        # one; `cb(screen, rgb_payload)` is called sync on the loop
        # thread for every frame that passes the rate cap above. Used
        # by the OpenRGB output manager + reserved for sACN/E1.31.
        self._frame_taps: list = []
        # Fallback default if a screen's settings haven't been
        # surfaced yet (race with first frame after startup).
        self._BROADCAST_INTERVAL_S = 1.0 / 30.0

    # ----- v2.4.1: WS keepalive / half-open socket detection -----
    #
    # Interval between server→client pings. Every inbound frame counts
    # as liveness, so on a healthy connection that's chatty in both
    # directions this rarely has to do real work.
    KEEPALIVE_INTERVAL_S = 20.0
    # A client that hasn't sent ANY frame within this window is treated
    # as gone and force-closed. Must be comfortably more than one ping
    # interval so a single dropped pong doesn't reap a live client;
    # 50 s gives us two full ping cycles of slack.
    CLIENT_IDLE_TIMEOUT_S = 50.0

    def note_client_seen(self, writer) -> None:
        """Refresh a client's last-seen stamp. Called from the WS read
        loop for every inbound frame (text, pong, or ignored binary) —
        anything arriving at all proves the socket is still live."""
        try:
            self._client_last_seen[writer] = self.loop.time()
        except Exception:
            pass

    async def _keepalive_loop(self):
        """Ping every client on an interval and reap the ones that have
        gone quiet.

        This is the server half of the sleep/resume fix (issue #2). The
        important part isn't the ping itself but the `await drain()`
        below: broadcast_frame() writes without draining, so on a
        half-open socket the bytes just pile into the transport buffer
        and no exception is ever raised. Draining forces the write
        through the kernel, which surfaces the dead peer as an
        OSError — at which point we can close the socket properly and
        let the page's existing onclose → reconnect path take over."""
        while True:
            try:
                await asyncio.sleep(self.KEEPALIVE_INTERVAL_S)
                now = self.loop.time()
                async with self._lock:
                    clients = [w for s in self.clients_by_screen.values()
                               for w in s]
                if not clients:
                    continue
                ping = encode_ping_frame()
                for w in clients:
                    # Never seen a frame from this client yet (just
                    # connected)? Seed the stamp so the first pass
                    # doesn't reap it before it has had a chance.
                    seen = self._client_last_seen.get(w)
                    if seen is None:
                        self._client_last_seen[w] = now
                        seen = now
                    if now - seen > self.CLIENT_IDLE_TIMEOUT_S:
                        print(f"[ws] client idle for "
                              f"{now - seen:.0f}s — closing (stale socket)")
                        await self.remove(w)
                        continue
                    try:
                        w.write(ping)
                        # The drain is the actual probe — see docstring.
                        await w.drain()
                    except Exception:
                        print("[ws] keepalive ping failed — closing client")
                        await self.remove(w)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[ws] keepalive loop error: {e}")

    def add_frame_tap(self, callback) -> None:
        """v1.4.0: register a `callback(screen: int, rgb_payload: bytes)`
        that fires for every UDP frame after the rate cap. Used by the
        OpenRGB output manager (and reserved for the sACN/E1.31 emitter
        on the roadmap) to mirror the wallpaper's live colour stream
        out to external consumers without coupling them to the WS
        broadcast path. Listeners must be cheap — they run sync on the
        asyncio loop thread."""
        if callable(callback) and callback not in self._frame_taps:
            self._frame_taps.append(callback)

    def remove_frame_tap(self, callback) -> None:
        try:
            self._frame_taps.remove(callback)
        except ValueError:
            pass

    def _broadcast_interval_for(self, screen: int) -> float:
        """Look up the broadcast interval (seconds) for a given
        screen. Reads the `frameRate` setting via the get_settings
        callback wired at construction time; gracefully falls back
        to the 30 Hz default when the setting is missing or invalid."""
        try:
            rate = int(self.get_settings(screen).get("frameRate", 30))
        except Exception:
            return self._BROADCAST_INTERVAL_S
        if rate <= 0 or rate > 240:
            return self._BROADCAST_INTERVAL_S
        return 1.0 / float(rate)

    def handle_client_message(self, screen: int, msg: dict):
        """Route a decoded JSON message from a wallpaper page. All widget
        mutations live here; future client→server messages slot in next to
        them. Runs on the asyncio loop thread."""
        t = msg.get("type")
        if t in ("widget-update", "widget-add", "widget-remove",
                 "widgets-set", "widgets-lock",
                 "quick-look-apply",
                 "setting-update", "viewport", "bridge-setting-update",
                 "system-action",
                 "preset-save", "preset-apply", "preset-clear",
                 "screen-reset",
                 "profile-add", "profile-update", "profile-remove"):
            try:
                self.on_widget_command(screen, msg)
            except Exception as e:
                print(f"[ws] command failed: {e}")
        # Unknown types are silently dropped — clients on a newer protocol
        # version shouldn't crash an older bridge.

    # ----- client lifecycle -----

    async def add(self, writer, screen: int, role: str = "wallpaper"):
        async with self._lock:
            self.clients_by_screen.setdefault(screen, set()).add(writer)
            # Side-table for client roles so the Status dialog can
            # count only the actual wallpaper pages and not e.g. the
            # user's own open Configurator tab.
            if not hasattr(self, "client_roles"):
                self.client_roles = {}
            self.client_roles[writer] = role
            # v2.4.1: seed the liveness stamp so _keepalive_loop() gives
            # this client a full idle window before considering it stale.
            self._client_last_seen[writer] = self.loop.time()
            total = sum(len(s) for s in self.clients_by_screen.values())
        print(f"[+] ws screen={screen} role={role} (total: {total})")
        # Push current settings immediately so the page can paint with the
        # right background / layout before the first frame arrives.
        try:
            settings = self.get_settings(screen)
            writer.write(encode_text_frame(json.dumps({
                "type": "settings", "screen": screen,
                "data": settings, "language": _CURRENT_LANG,
                "screenCount": int(self.get_screen_count()),
                "profiles": self._get_profiles_for_push(),
                "bridge": self.get_bridge_state(),
                # v1.5.0-beta plugin API: catalogue of discovered
                # 3rd-party widget plugins. The Configurator surfaces
                # them in the picker as `plugin/<name>` entries, and
                # the wallpaper page renders each instance into a
                # sandboxed iframe.
                "plugins": self._get_plugin_catalogue(),
                "wsProtocolVersion": WS_PROTOCOL_VERSION,
            })))
        except Exception as e:
            print(f"[ws] initial settings push failed: {e}")
        # Also push the current paused state so a page that connects mid-
        # game starts paused (rather than rendering a brief flash of glow
        # before the next state change fires).
        try:
            writer.write(encode_text_frame(json.dumps({"type": "paused", "paused": bool(self.get_paused())})))
        except Exception as e:
            print(f"[ws] initial paused push failed: {e}")

    async def remove(self, writer):
        async with self._lock:
            if hasattr(self, "client_roles"):
                self.client_roles.pop(writer, None)
            # v2.2.2: drop any pending slow-client skip counter so the
            # dict doesn't grow over a long uptime as clients churn.
            self._client_skip_count.pop(writer, None)
            # v2.4.1: same for the keepalive liveness stamp.
            self._client_last_seen.pop(writer, None)
            removed_from = None
            for screen, clients in list(self.clients_by_screen.items()):
                if writer in clients:
                    clients.discard(writer)
                    if removed_from is None:
                        removed_from = screen
            # v2.4.1: always close the transport, even when the writer
            # wasn't in any screen set. remove() is now called from the
            # keepalive reaper as well as the read loop, so it can race
            # with itself; a second call must still be a safe no-op but
            # must never leave a stale socket open.
            try: writer.close()
            except Exception: pass
            if removed_from is not None:
                total = sum(len(s) for s in self.clients_by_screen.values())
                print(f"[-] ws screen={removed_from} (total: {total})")

    def has_any_clients(self) -> bool:
        """Lock-free snapshot of whether ANY wallpaper page is currently
        connected (any screen, any role). Pollers use this as an idle
        gate so they don't drive their respective IPC pipelines (SMTC,
        LHM HTTP, psutil collect + JSON broadcast) when no widget on a
        live page can render the result. CPython dict-values iteration
        is atomic; race with an in-flight add() at worst drops one
        tick, recovered next second."""
        try:
            for s in self.clients_by_screen.values():
                if s:
                    return True
            return False
        except Exception:
            return True   # fail open — prefer wasted poll over silent break

    def has_clients_for(self, screen: int) -> bool:
        """Lock-free snapshot of whether any wallpaper page is currently
        listening on a given screen. Used by UdpReceiver.datagram_received
        as a sync short-circuit: if nobody's listening, skip the whole
        broadcast pipeline (no asyncio.Task, no frame encode). CPython
        dict reads are atomic so we don't need to await self._lock here
        — a false negative just drops one frame, which the next datagram
        recovers from instantly."""
        try:
            s = self.clients_by_screen.get(int(screen))
            return bool(s)
        except Exception:
            return False

    # ----- broadcasting (called from asyncio loop) -----

    # v1.2.18: backpressure threshold for the per-client TCP send
    # buffer. Above this we drop frames for that client instead of
    # adding to its pending writes. The wallpaper page reads WS
    # binary frames at variable speed (heavy widget tick + paint can
    # block the main thread); without backpressure the asyncio
    # StreamWriter's buffer grew indefinitely → 590 MB resident
    # observed in v1.1 / early v1.2 testing. 256 KiB ≈ 80 frames at
    # the typical 16×9×3 = 432-byte single-packet payload, or ~5
    # full-grid 32×32 frames; plenty of headroom for a brief
    # client-side hitch without dropping anything visible, but caps
    # the leak.
    _CLIENT_WRITE_BUFFER_LIMIT = 256 * 1024
    # v2.2.2: backpressure-skip cap. Pre-2.2.2 a client whose
    # transport buffer stayed permanently over the limit was skipped
    # forever — never closed, never removed. A backgrounded browser
    # tab that throttled its event loop could leak ~256 KiB indefinitely
    # while we kept it in clients_by_screen. After this many consecutive
    # skips across all push paths we treat the client as dead and
    # close it. 200 skips ≈ 6 s at 30 Hz broadcast, ≈ 20 s at the
    # settings-push rate — a real user momentary stall stays well under
    # this; a truly stuck client gets reaped.
    _SLOW_SKIP_FORCE_CLOSE_THRESHOLD = 200

    def _client_should_skip(self, w) -> bool:
        """Per-client backpressure decision: returns True when the
        transport buffer is over the limit AND the consecutive skip
        counter hasn't tripped the force-close threshold. Tracks the
        counter as a side effect so a series of skips eventually reaps
        the client instead of leaking the buffer forever. Returns False
        (= 'write the frame') in the normal happy path, which also
        resets the counter."""
        tr = w.transport
        if tr is None:
            return False
        # v2.4.1: a transport that's already closing must not be written
        # to. Pre-2.4.1 this only surfaced as an exception on write();
        # after a sleep/resume the socket can sit closing for a while,
        # so check explicitly and let the caller reap it.
        if tr.is_closing():
            return False
        if tr.get_write_buffer_size() <= self._CLIENT_WRITE_BUFFER_LIMIT:
            # Healthy — reset the consecutive-skip count.
            self._client_skip_count.pop(w, None)
            return False
        # Over the limit: count this skip, force-close if we've
        # crossed the threshold (caller treats us as dead).
        n = self._client_skip_count.get(w, 0) + 1
        self._client_skip_count[w] = n
        if n >= self._SLOW_SKIP_FORCE_CLOSE_THRESHOLD:
            try:
                tr.close()
            except Exception:
                pass
            self._client_skip_count.pop(w, None)
            return False  # caller will catch the closed transport via .write()
        return True

    async def broadcast_frame(self, screen: int, payload: bytes):
        # Skip while paused — no point shipping per-frame UDP-derived
        # bytes when the wallpaper page is going to drop them anyway. The
        # plugin keeps sending, the bridge just absorbs.
        try:
            if self.get_paused():
                return
        except Exception:
            pass
        # v1.2.12: per-screen outgoing rate cap, driven by the
        # screen's `frameRate` setting (20 / 30 / 60 Hz). Closes the
        # pipeline at the source so a chatty plugin (Solid Color at
        # ~200 fps) doesn't make WebView2 decode 5×-6× more WS
        # frames than the page will ever render.
        now = self.loop.time()
        last = self._last_broadcast_per_screen.get(screen, 0.0)
        if now - last < self._broadcast_interval_for(screen):
            return
        self._last_broadcast_per_screen[screen] = now
        # v1.4.0: frame taps. Any registered listener (currently the
        # OpenRGB output manager, future sACN/E1.31 emitter etc.) sees
        # the raw RGB payload before we wrap it for WS. Tap runs sync
        # on the loop thread — listeners must be cheap; anything that
        # does I/O should hand off to a worker.
        for tap in self._frame_taps:
            try:
                tap(screen, payload)
            except Exception as e:
                print(f"[broadcast] frame tap failed: {e}")
        async with self._lock:
            clients = list(self.clients_by_screen.get(screen, ()))
            # v1.5.0-beta hotfix: exclude `role=configurator` clients
            # from per-frame glow broadcasts. The Configurator's main
            # WS drops binary frames in its onmessage handler anyway,
            # but the browser still allocates an ArrayBuffer per
            # arrival. At 60-200 Hz × 4 screens that's 6 MB/s heap
            # churn on the user's tab (visible in DevTools as the
            # sawtooth heap growth that pegs Animation work to
            # ~100 %). Skipping them server-side cuts the wallpaper-
            # page render pipeline's overhead too: encode_binary_frame
            # runs once but isn't fanned to no-op receivers.
            roles = getattr(self, "client_roles", {}) or {}
            clients = [w for w in clients
                       if roles.get(w, "wallpaper") != "configurator"]
        if not clients:
            return
        frame = encode_binary_frame(payload)
        dead = []
        for w in clients:
            try:
                # v1.2.18: per-client backpressure. transport.get_write_buffer_size()
                # is the StreamWriter's pending-bytes counter; if it's
                # above our cap the client is reading slower than we're
                # writing and adding more frames just leaks memory. The
                # plugin sends a fresh frame every ~16 ms anyway, so a
                # dropped frame here costs the user at most one render.
                if self._client_should_skip(w):
                    continue
                w.write(frame)
            except Exception:
                dead.append(w)
        for w in dead:
            await self.remove(w)

    async def push_pause(self, paused: bool):
        async with self._lock:
            all_clients = [w for clients in self.clients_by_screen.values() for w in clients]
        if not all_clients:
            return
        msg = json.dumps({"type": "paused", "paused": bool(paused)})
        frame = encode_text_frame(msg)
        dead = []
        for w in all_clients:
            try:
                if self._client_should_skip(w):
                    continue
                w.write(frame)
            except Exception:
                dead.append(w)
        for w in dead:
            await self.remove(w)
        print(f"[push] paused={paused} -> {len(all_clients)} client(s)")

    def push_pause_threadsafe(self, paused: bool):
        asyncio.run_coroutine_threadsafe(self.push_pause(paused), self.loop)

    async def push_reload_all(self):
        """Tell every connected wallpaper page to `location.reload()`.
        Skips the Configurator (role=configurator) so we don't yank
        the user's open settings tab from under them. Used by the
        tray's *Reload wallpaper pages* entry to force a refresh
        after a v0.X.Y upgrade so users don't have to manually re-
        import the Lively/WE bundle for every JS update."""
        async with self._lock:
            roles = getattr(self, "client_roles", {}) or {}
            all_clients = [w for clients in self.clients_by_screen.values() for w in clients]
            # Filter to wallpaper-role clients only.
            targets = [w for w in all_clients if roles.get(w, "wallpaper") == "wallpaper"]
        if not targets:
            return
        msg = json.dumps({"type": "reload"})
        frame = encode_text_frame(msg)
        dead = []
        for w in targets:
            try:
                if self._client_should_skip(w):
                    continue
                w.write(frame)
            except Exception:
                dead.append(w)
        for w in dead:
            await self.remove(w)
        print(f"[push] reload -> {len(targets)} wallpaper page(s)")

    def push_reload_all_threadsafe(self):
        asyncio.run_coroutine_threadsafe(self.push_reload_all(), self.loop)

    async def push_settings(self, screen: int, settings: dict):
        async with self._lock:
            clients = list(self.clients_by_screen.get(screen, ()))
        if not clients:
            return
        # Surface the active UI language alongside the per-screen data so
        # the Configurator can localise itself off a single push.
        msg = json.dumps({"type": "settings", "screen": screen,
                          "data": settings, "language": _CURRENT_LANG,
                          "screenCount": int(self.get_screen_count()),
                          "profiles": self._get_profiles_for_push(),
                          "bridge": self.get_bridge_state(),
                          "wsProtocolVersion": WS_PROTOCOL_VERSION})
        frame = encode_text_frame(msg)
        dead = []
        for w in clients:
            try:
                if self._client_should_skip(w):
                    continue
                w.write(frame)
            except Exception:
                dead.append(w)
        for w in dead:
            await self.remove(w)
        print(f"[push] settings -> screen={screen} ({len(clients)} clients)")

    # ----- thread-safe entry from non-asyncio threads (tray callback) -----

    def push_settings_threadsafe(self, screen: int, settings: dict):
        asyncio.run_coroutine_threadsafe(self.push_settings(screen, settings), self.loop)

    def _get_profiles_for_push(self) -> list:
        """Pull the latest profiles list from the runtime config. Returns
        an empty list when the runtime hasn't been wired in yet (defensive
        — the Broadcaster's request handlers and the WS-open path can fire
        before bridge_runtime is set in start())."""
        rt = getattr(self, "bridge_runtime", None)
        if rt is None:
            return []
        try:
            with rt.config_lock:
                return list(rt.config.get("profiles", []) or [])
        except Exception:
            return []

    def _get_plugin_catalogue(self) -> list:
        """v1.5.0-beta plugin API: list of {name, label, iconSvg,
        defaultSize, defaultOptions, version, author, description}
        the wallpaper page + Configurator use to render plugin
        widgets. Empty list when no plugins are installed or the
        registry isn't wired yet."""
        reg = getattr(self, "plugin_registry", None)
        if reg is None:
            return []
        try:
            # Strip the absolute `folder` path before pushing — the
            # wallpaper page + Configurator address plugins via the
            # `/plugins/<name>/…` URL, never via the on-disk path.
            return [{k: v for k, v in p.items() if k != "folder"}
                    for p in reg.list_plugins()]
        except Exception:
            return []

    async def push_sysstats(self, snapshot: dict):
        """Broadcast a single sysstats payload to every connected client.
        snapshot keys: cpu (0..100), ram (0..100), netDown / netUp (bytes/s),
        uptime (seconds), and 'ts' (epoch ms).
        v1.2.7: snapshot client list FIRST and skip the JSON encode +
        text-frame wrap if nobody's listening. Previously the bridge
        json.dumps()'d a fresh sysstats payload every second forever
        even when no wallpaper page was connected — small per-call,
        but adds heap pressure across a 12 h session. Also applies
        the per-client 256 KiB backpressure cap broadcast_frame uses.
        """
        async with self._lock:
            all_clients = [w for clients in self.clients_by_screen.values() for w in clients]
        if not all_clients:
            return
        msg = json.dumps({"type": "sysstats", "data": snapshot})
        frame = encode_text_frame(msg)
        dead = []
        for w in all_clients:
            try:
                if self._client_should_skip(w):
                    continue
                w.write(frame)
            except Exception: dead.append(w)
        for w in dead:
            await self.remove(w)

    def push_sysstats_threadsafe(self, snapshot: dict):
        asyncio.run_coroutine_threadsafe(self.push_sysstats(snapshot), self.loop)

    # ----- TCP accept handler (HTTP or WS upgrade) -----

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Accept one HTTP request (or a WS upgrade) and dispatch it.

        Every route below used to be an inline `if` in this function,
        which had grown to 1611 lines — 13 % of this file in a single
        body, and the path every request the bridge serves goes through.
        The bodies moved into `_route_*` methods verbatim; only the
        dispatch moved.

        HOW A ROUTE SIGNALS THAT IT HANDLED THE REQUEST

        By closing the writer, not by returning a value. Every handler
        already ends its successful path with `writer.close()` — all 32
        of them, including the two /api ones that delegate to
        `_handle_api_request` — so the existing code already carries the
        signal. The alternative (return a sentinel) would have meant
        rewriting 55 bare `return` statements inside the handler bodies,
        several of which sit in nested helper functions where `return`
        means something entirely different. That edit is the kind whose
        mistakes are silent, and there was no reason to make it.

        FALL-THROUGH IS LOAD-BEARING

        Four routes match on a path prefix but decline once they inspect
        it further — POST /screen/<N>/… when the third segment is
        neither "background" nor "settings", and GET /wallpaper/… and
        /plugins/… when the file does not resolve. They leave the writer
        open and the chain continues, which is how /api/v1/… still gets
        reached after the broad `if method == "GET"` block above it.
        tests/test_http_routing.py pins that behaviour.

        ORDER MATTERS. `/config` is matched exactly rather than by
        prefix so it cannot swallow `/configurator`; several routes
        overlap similarly. Reordering these calls changes which handler
        answers what.
        """
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError):
            writer.close()
            return

        headers = parse_http_headers(request)
        first_line = request.split(b"\r\n", 1)[0].decode("latin1", "replace")
        parts = first_line.split(" ", 2)
        method = parts[0] if len(parts) >= 1 else ""
        target = parts[1] if len(parts) >= 2 else ""

        if headers.get(b"upgrade", b"").lower() == b"websocket":
            return await self._serve_websocket(reader, writer, request, target)

        await self._route_image(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_config(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_screen_background(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_screen_settings(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_builder(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_widgets_skins(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_hwmon_sensors(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_health(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_openrgb_status(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_channel_status(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_library_list(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_library_file(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_library_thumb(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_library_upload(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_library_delete(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_library_pin(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_library_category(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_library_transform(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_library_openfolder(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_packs_list(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_packs_install(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_packs_uninstall(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_library_tags(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_library_reorder(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_backup(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_restore(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_help(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_help_images(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_configurator(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_wallpaper_assets(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_plugins(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_api_openapi_json(method, target, headers, reader, writer)
        if writer.is_closing():
            return
        await self._route_api_v1(method, target, headers, reader, writer)
        if writer.is_closing():
            return

        http_error(writer, 404, "not found")
        try: await writer.drain()
        except Exception: pass
        try: writer.close()
        except Exception: pass

    async def _route_image(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        if method == "GET" and target.startswith("/image"):
            query = target.split("?", 1)[1] if "?" in target else ""
            range_hdr = headers.get(b"range", b"").decode("latin-1")
            try:
                await http_serve_image(writer, query, range_hdr, request_headers=headers)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_config(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # The SignalRGB plugin XHRs here on every Update() tick to learn how
        # many controllers to announce. Plugin sandbox has no service-level
        # settings UI, so the bridge owns this knob — change it via tray.
        # Match `/config` exactly (with optional query string) — `startswith`
        # would otherwise eat `/configurator` and silently serve JSON in its
        # place.
        if method == "GET" and target.split("?", 1)[0] in ("/config", "/config/"):
            try:
                # The plugin uses screenCount to decide how many virtual
                # controllers to announce. The per-screen viewport[] sidecar
                # lets the plugin auto-derive a matching grid aspect ratio
                # — e.g. 3840×1080 ultrawide gets cols≈3.56×rows instead of
                # a square — so the SignalRGB device's effect samples scale
                # to the actual monitor instead of always being square.
                count = int(self.get_screen_count())
                screens = []
                for i in range(count):
                    try:
                        s = self.get_settings(i)
                        m = s.get("mirrorOf")
                        # v1.2.10: pass through monitorSetup so the Builder
                        # can pick it up via its /config poll (Builder has
                        # no persistent WS so the settings push doesn't
                        # reach it). Without this, Configurator-side span
                        # changes were silently ignored by the Builder.
                        ms = s.get("monitorSetup")
                        if not isinstance(ms, dict):
                            ms = {"mode": "single", "orientations": ["landscape"]}
                        # v1.2.12: per-screen measured plugin send rate.
                        # 0.0 until the UdpReceiver's first 1 s window
                        # closes (i.e. plugin not running yet, or just
                        # started). Configurator displays this next to
                        # the frameRate cap dropdown as orientation.
                        try:
                            mfps = float(self.udp_provider.get_measured_fps(i)) \
                                if self.udp_provider else 0.0
                        except Exception:
                            mfps = 0.0
                        screens.append({
                            "viewportW": int(s.get("viewportW") or 0),
                            "viewportH": int(s.get("viewportH") or 0),
                            # bgImage is included so the Configurator's
                            # Overview card can paint mini-thumbnails for
                            # every screen without opening a WS per tab.
                            "bgImage":   str(s.get("bgImage") or ""),
                            # mirrorOf surfaces in the overview as a small
                            # indicator on mirroring tiles.
                            "mirrorOf":  (int(m) if isinstance(m, int) else None),
                            "monitorSetup": ms,
                            "measuredPluginFps": round(mfps, 1),
                        })
                    except Exception:
                        screens.append({"viewportW": 0, "viewportH": 0,
                                        "bgImage": "", "mirrorOf": None,
                                        "monitorSetup": {"mode": "single",
                                                         "orientations": ["landscape"]},
                                        "measuredPluginFps": 0.0})
                payload = json.dumps({
                    "screenCount": count,
                    "screens": screens,
                    "language": _CURRENT_LANG,
                }).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    f"Access-Control-Allow-Origin: {_acao(headers)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_screen_background(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # POST /screen/<N>/background — receive a PNG from the builder
        # and apply it as that screen's background. Body is the raw PNG
        # bytes (no multipart wrapper; Content-Type: image/png). We
        # save with a millisecond-timestamped filename so the wallpaper
        # page re-fetches a fresh URL (avoids stale-image cache hits).
        if method == "POST" and target.startswith("/screen/"):
            parts = target.split("?", 1)[0].strip("/").split("/")
            # ["screen", "<N>", "background"]
            if len(parts) >= 3 and parts[0] == "screen" and parts[2] == "background":
                try:
                    screen_idx = int(parts[1])
                except ValueError:
                    screen_idx = -1
                if 0 <= screen_idx < N_SCREENS:
                    try:
                        content_length = int(headers.get(b"content-length", b"0") or 0)
                    except ValueError:
                        content_length = 0
                    if 0 < content_length <= MAX_BACKGROUND_UPLOAD_BYTES:
                        try:
                            body = await reader.readexactly(content_length)
                            # v1.2.13: magic-byte sniff so an arbitrary
                            # binary payload pretending to be a PNG via
                            # Content-Type can't land in the screens/
                            # folder. PNG + JPEG + WebP + GIF + the
                            # ISO-BMFF video containers the wallpaper
                            # page can play back.
                            valid = (
                                body[:8] == b"\x89PNG\r\n\x1a\n" or
                                body[:3] == b"\xff\xd8\xff" or
                                (body[:4] == b"RIFF" and body[8:12] == b"WEBP") or
                                body[:6] in (b"GIF87a", b"GIF89a") or
                                body[:4] == b"\x1aE\xdf\xa3" or
                                (len(body) > 12 and body[4:8] == b"ftyp")
                            )
                            if not valid:
                                http_error(writer, 400,
                                    "background payload not recognised (PNG / JPEG / WebP / GIF / MP4 / WebM / MOV expected)")
                                try: await writer.drain()
                                except Exception: pass
                                try: writer.close()
                                except Exception: pass
                                return
                            ok = self.update_background(screen_idx, body)
                            if ok:
                                await self.push_settings(screen_idx, self.get_settings(screen_idx))
                                payload = b'{"ok":true}'
                            else:
                                payload = b'{"ok":false}'
                            head = (
                                "HTTP/1.1 200 OK\r\n"
                                "Content-Type: application/json\r\n"
                                f"Content-Length: {len(payload)}\r\n"
                                "Cache-Control: no-store\r\n"
                                "Connection: close\r\n\r\n"
                            ).encode()
                            writer.write(head + payload)
                        except asyncio.IncompleteReadError:
                            http_error(writer, 400, "incomplete body")
                        except Exception as e:
                            http_error(writer, 500, f"upload failed: {e}")
                    else:
                        http_error(writer, 400, f"bad content-length: {content_length} (max {MAX_BACKGROUND_UPLOAD_BYTES})")
                else:
                    http_error(writer, 404, f"unknown screen index: {screen_idx} (allowed 0..{N_SCREENS-1})")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return

    async def _route_screen_settings(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # POST /screen/<N>/settings — body is JSON {key1: val1, key2: val2}
        # for a batch setting update on screen N. Used by the Configurator's
        # "Apply to all screens" buttons: the open WS is bound to one
        # screen, so cross-screen updates need an out-of-band channel.
        # Each key is filtered through the same _SETTABLE_SCREEN_KEYS
        # whitelist `setting-update` uses, so the HTTP path can't grow
        # the attack surface past what the WS already exposes.
        if method == "POST" and target.startswith("/screen/"):
            parts2 = target.split("?", 1)[0].strip("/").split("/")
            if len(parts2) >= 3 and parts2[0] == "screen" and parts2[2] == "settings":
                try:
                    screen_idx = int(parts2[1])
                except ValueError:
                    screen_idx = -1
                if 0 <= screen_idx < N_SCREENS:
                    try:
                        content_length = int(headers.get(b"content-length", b"0") or 0)
                    except ValueError:
                        content_length = 0
                    if not (0 < content_length <= 65536):
                        http_error(writer, 400, f"bad content-length: {content_length}")
                        try: await writer.drain()
                        except Exception: pass
                        try: writer.close()
                        except Exception: pass
                        return
                    try:
                        body = await reader.readexactly(content_length)
                        req = json.loads(body.decode("utf-8"))
                        if not isinstance(req, dict):
                            raise ValueError("body must be a JSON object")
                        # update_screen_setting lives on BridgeRuntime, not
                        # here. This called self.update_screen_setting and
                        # therefore raised AttributeError on every request —
                        # the route has never worked. It predates the v2.4.4
                        # route split (verified against the v2.4.4-beta.4
                        # tag) and stayed hidden because the Configurator's
                        # "apply to all screens" buttons are the only
                        # caller, and a failure there looks like the click
                        # not registering.
                        runtime = getattr(self, "bridge_runtime", None)
                        if runtime is None:
                            http_error(writer, 503, "bridge runtime not wired",
                                       request_headers=headers)
                            try: await writer.drain()
                            except Exception: pass
                            try: writer.close()
                            except Exception: pass
                            return
                        applied = 0
                        for key, value in req.items():
                            snap = runtime.update_screen_setting(screen_idx, str(key), value)
                            if snap is not None:
                                applied += 1
                        payload = json.dumps({"ok": True, "applied": applied}).encode("utf-8")
                        head = (
                            "HTTP/1.1 200 OK\r\n"
                            "Content-Type: application/json\r\n"
                            f"Content-Length: {len(payload)}\r\n"
                            "Cache-Control: no-store\r\n"
                            "Connection: close\r\n\r\n"
                        ).encode()
                        writer.write(head + payload)
                    except asyncio.IncompleteReadError:
                        http_error(writer, 400, "incomplete body")
                    except Exception as e:
                        http_error(writer, 500, f"settings update failed: {e}")
                else:
                    http_error(writer, 404, f"unknown screen index: {screen_idx}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return

    async def _route_builder(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # Local in-browser wallpaper builder. Opened via the tray "Build
        # Wallpaper…" menu item. Pure client-side canvas app — we just
        # serve the static HTML file bundled alongside the exe.
        if method == "GET" and target.split("?", 1)[0] in ("/builder", "/builder/"):
            try:
                builder_path = _resource_path("builder.html")
                data = builder_path.read_bytes()
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    f"Content-Length: {len(data)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + data)
            except FileNotFoundError:
                http_error(writer, 500, "builder.html not bundled with this build")
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_widgets_skins(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # Wallpaper library: list + individual file. Files live under
        # %LOCALAPPDATA%\SignalRGBWallpaper\library\ — the installer drops
        # the generated starter set there on install, and the user can
        # also add their own PNGs by hand. `library.json` carries
        # metadata (label, thumb path, etc.); the listing endpoint just
        # streams that file. Individual /library/<name> serves the PNG /
        # thumb bytes back; the Configurator builds img URLs off this
        # path. Path traversal is blocked by rejecting any name with a
        # path separator or dot-dot.
        # v2.3.4-beta: GET /widgets/skins[?type=<type>] — surfaces the
        # bundled skin catalog so the Configurator's widget-config
        # modal can offer a "Skin" picker without duplicating the
        # list. Catalog is hardcoded server-side and mirrored from
        # wallpaper/index.html's SKIN_CATALOG_MIRROR; keep both in
        # sync when adding a new skin (a future iteration can move
        # to dynamic discovery via the wallpaper page on WS open).
        if method == "GET" and target.split("?", 1)[0] == "/widgets/skins":
            qs = target.split("?", 1)[1] if "?" in target else ""
            params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            want = urllib.parse.unquote(params.get("type", ""))
            catalog = {
                "weather": [
                    {"id": "default", "label": "Default"},
                    {"id": "compact", "label": "Compact"},
                    {"id": "hexagon", "label": "Hexagon"},
                ],
            }
            if want:
                resp_obj = {"type": want, "skins": catalog.get(want, [])}
            else:
                resp_obj = {"catalog": catalog}
            try:
                payload = json.dumps(resp_obj).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    f"Access-Control-Allow-Origin: {_acao(headers)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_hwmon_sensors(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # /hwmon/sensors — flat list of every sensor LibreHardwareMonitor
        # is reporting, plus a small status block. The Configurator's
        # hardware-sensor widget options modal calls this to populate
        # the sensor-path dropdown. Returns an empty list when LHM
        # isn't running (status.online = false).
        if method == "GET" and target.split("?", 1)[0] == "/hwmon/sensors":
            try:
                hw = getattr(self, "hwmon_provider", None)
                snap = hw.get_snapshot() if hw else {}
                status = hw.get_status() if hw else {"online": False, "sensorCount": 0}
                items = [
                    {"path": p, "value": entry.get("value"),
                     "unit": entry.get("unit"), "raw": entry.get("raw")}
                    for p, entry in sorted(snap.items())
                ]
                payload = json.dumps({"status": status, "items": items}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    f"Access-Control-Allow-Origin: {_acao(headers)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_health(self, method, target, headers, reader, writer):
        """GET /health — is this install actually working end to end?

        v2.4.11. get_health_status() has existed since v0.8.9 but was
        reachable only through the tray's System-status dialog, which a
        first-time user has no reason to open. Meanwhile the
        Configurator's "connected" pill reports the Configurator's own
        socket to the bridge, which reads to a novice as "everything is
        fine" while the SignalRGB half of the chain can be entirely
        dead.

        Same snapshot, now over HTTP so the Configurator can show it
        where people actually look.
        """
        if method == "GET" and target.split("?", 1)[0] == "/health":
            try:
                runtime = getattr(self, "bridge_runtime", None)
                if runtime is None:
                    snap = {"available": False, "reason": "bridge runtime not wired"}
                else:
                    snap = runtime.get_health_status()
                    snap["available"] = True
                payload = json.dumps(snap).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    f"Access-Control-Allow-Origin: {_acao(headers)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}",
                           request_headers=headers)
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_openrgb_status(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v1.4.0-beta: status snapshot for the OpenRGB output channel.
        # Configurator polls this every few seconds while its OpenRGB
        # card is visible to render the connection state + device list
        # without taking a WS round-trip per refresh.
        if method == "GET" and target.split("?", 1)[0] == "/openrgb/status":
            try:
                provider = getattr(self, "openrgb_provider", None)
                if provider is None:
                    snap = {
                        "available": False,
                        "enabled":   False,
                        "connected": False,
                        "lastError": "manager not wired",
                        "devices":   [],
                    }
                else:
                    snap = provider.get_status()
                payload = json.dumps(snap).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    f"Access-Control-Allow-Origin: {_acao(headers)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}",
                           request_headers=headers)
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_channel_status(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v1.5.0-beta: status endpoints for the three new channels.
        # Same single-shot polling pattern as /openrgb/status — Configurator
        # tickles them every 2 s while their sub-panel is visible.
        _v15_status_routes = {
            "/openrgb-input/status":  "openrgb_input_provider",
            # v1.6.2-beta: SDK-server status. Same poll pattern.
            "/openrgb-sdk/status":    "openrgb_sdk_provider",
            "/sacn/status":           "sacn_output_provider",
            "/sacn-input/status":     "sacn_input_provider",
            "/sources/status":        "source_provider",
            "/mqtt/status":           "mqtt_provider",
            "/plugins":               "plugin_provider",
        }
        if method == "GET" and target.split("?", 1)[0] in _v15_status_routes:
            attr = _v15_status_routes[target.split("?", 1)[0]]
            try:
                provider = getattr(self, attr, None)
                snap = (provider.get_status() if provider
                        else {"available": False, "lastError": "manager not wired"})
                payload = json.dumps(snap).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    f"Access-Control-Allow-Origin: {_acao(headers)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}",
                           request_headers=headers)
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_library_list(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v2.0.1: /library/packs/* HTTP endpoints removed (see
        # the note above library_dir() for why).

        if method == "GET" and target.split("?", 1)[0] == "/library/list":
            try:
                lib_dir = library_dir()
                cat_path = lib_dir / "library.json"
                if cat_path.exists():
                    payload = cat_path.read_bytes()
                else:
                    payload = b'{"version":1,"items":[]}'
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    f"Access-Control-Allow-Origin: {_acao(headers)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_library_file(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""
        if method == "GET" and target.split("?", 1)[0].startswith("/library/"):
            # v1.2.13: defence in depth. The pre-v1.2.13 check rejected
            # literal `/ \ ..` but missed the URL-encoded equivalents
            # (`%2F` `%5C` `%2E%2E`). Path.resolve() below already
            # contains the escape because we re-anchor against
            # library_dir() and refuse anything outside, but failing
            # the request before any filesystem access reduces noise
            # and is a less attractive target. Unquote first, then
            # apply the original literal check, then anchor.
            raw = target.split("?", 1)[0][len("/library/"):]
            try:
                name = urllib.parse.unquote(raw)
            except Exception:
                name = raw
            if (not name
                    or "/" in name or "\\" in name or ".." in name
                    or name.startswith(".")):
                http_error(writer, 400, "bad library filename",
                           request_headers=headers)
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                # Anchor under library_dir() and reject anything whose
                # resolved path escapes it (symlink shenanigans).
                lib = library_dir().resolve()
                fp = (lib / name).resolve()
                try:
                    fp.relative_to(lib)
                except ValueError:
                    http_error(writer, 400, "library path escapes root",
                               request_headers=headers)
                    try: await writer.drain()
                    except Exception: pass
                    try: writer.close()
                    except Exception: pass
                    return
                fp = library_dir() / name
                if not fp.exists() or not fp.is_file():
                    http_error(writer, 404, "library item not found")
                else:
                    # v1.7.5: mtime+size ETag with 304 short-circuit.
                    # Previous 24 h Cache-Control kept stale thumbs in
                    # the CEF cache after a regen of the bundle. Now
                    # the browser revalidates on every request — when
                    # the bytes haven't changed we answer 304 (~70 B,
                    # no body); when they have, the full image flows.
                    st = fp.stat()
                    etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
                    if_none = headers.get(b"if-none-match", b"").decode(
                        "latin-1", "ignore").strip()
                    if if_none and if_none == etag:
                        head = (
                            "HTTP/1.1 304 Not Modified\r\n"
                            f"ETag: {etag}\r\n"
                            "Cache-Control: no-cache\r\n"
                            f"Access-Control-Allow-Origin: {_acao(headers)}\r\n"
                            "Connection: close\r\n\r\n"
                        ).encode()
                        writer.write(head)
                    else:
                        body = fp.read_bytes()
                        ct, _ = mimetypes.guess_type(str(fp))
                        if not ct: ct = "application/octet-stream"
                        head = (
                            "HTTP/1.1 200 OK\r\n"
                            f"Content-Type: {ct}\r\n"
                            f"Content-Length: {len(body)}\r\n"
                            f"ETag: {etag}\r\n"
                            "Cache-Control: no-cache\r\n"
                            f"Access-Control-Allow-Origin: {_acao(headers)}\r\n"
                            "Connection: close\r\n\r\n"
                        ).encode()
                        writer.write(head + body)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_library_thumb(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # POST /library/thumb — attach a poster thumbnail to an existing
        # library entry. Body is the raw PNG, query string carries
        # ?name=<slug> matching the catalogue id. Saved as <slug>.thumb.png
        # so the existing _library_rebuild_catalogue logic picks it up
        # as the entry's thumb on the next /library/list call. Used by
        # the Configurator to give video-format library items a still-
        # frame poster so the Library tile renders something instead of
        # the broken CSS `background-image: url(*.mp4)` placeholder.
        if method == "POST" and target.split("?", 1)[0] == "/library/thumb":
            qs = target.split("?", 1)[1] if "?" in target else ""
            params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            slug = urllib.parse.unquote(params.get("name", "")).strip()
            # The slug must look like one _library_slug() would have
            # produced — lowercase ascii / digits / `_-`. Anything else
            # is path-traversal-shaped and rejected.
            if (not slug
                    or len(slug) > 96
                    or not all(c in _LIBRARY_SAFE_CHARS for c in slug)):
                http_error(writer, 400, "missing or bad 'name' parameter")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            # Thumbs are tiny — cap at 4 MiB so a buggy client can't
            # tie up the upload path with a giant blob.
            if not (0 < content_length <= 4 * 1024 * 1024):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                if body[:8] != b"\x89PNG\r\n\x1a\n":
                    http_error(writer, 400, "thumb body must be PNG")
                    try: await writer.drain()
                    except Exception: pass
                    try: writer.close()
                    except Exception: pass
                    return
                fp = library_dir() / (slug + ".thumb.png")
                fp.write_bytes(body)
                # v2.2.2: catalogue rebuild moved to executor — was
                # freezing the event loop on large libraries (same
                # pattern as the v2.2.1 autocut / transform fix).
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, _library_rebuild_catalogue, library_dir())
                payload = json.dumps({"ok": True, "file": fp.name}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 500, f"thumb upload failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_library_upload(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # POST /library/upload — body is the raw PNG; query string carries
        # ?name=<label>. We slug the label, drop into the user-writable
        # library dir, regenerate library.json so future /library/list
        # calls include the new entry. Bytes capped via the same
        # MAX_BACKGROUND_UPLOAD_BYTES the screen uploader uses.
        if method == "POST" and target.split("?", 1)[0] == "/library/upload":
            qs = target.split("?", 1)[1] if "?" in target else ""
            params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            label = urllib.parse.unquote(params.get("name", "Untitled")).strip() or "Untitled"
            # v1.6.1-beta library categories: the uploader can declare
            # the new entry's category via ?category=template / background
            # / both. Builder uses "template" for raw source uploads,
            # Library tile-add uses "background". Anything unknown
            # falls back to "both" so old clients still get the v1.5
            # behaviour.
            upload_category = params.get("category", "both")
            if upload_category not in ("background", "template", "both"):
                upload_category = "both"
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= MAX_BACKGROUND_UPLOAD_BYTES):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                # Sniff format from the first bytes. PNG / JPEG / WebP
                # / GIF still + animated for images; MP4 / WebM / MOV
                # for video (v1.2-dev). Anything else gets a 400 so
                # we don't silently accept random binaries into the
                # library and have the wallpaper page choke on them.
                ext = None
                if   body[:8] == b"\x89PNG\r\n\x1a\n":     ext = ".png"
                elif body[:3] == b"\xff\xd8\xff":          ext = ".jpg"
                elif body[:4] == b"RIFF" and body[8:12] == b"WEBP":  ext = ".webp"
                elif body[:6] in (b"GIF87a", b"GIF89a"):   ext = ".gif"
                elif body[:4] == b"\x1aE\xdf\xa3":         ext = ".webm"
                # MP4 / MOV use ISO BMFF container — `ftyp` box at
                # offset 4. Subtype byte tells us mp4 vs mov vs m4v
                # but for filing they all play back fine through the
                # <video> element so we just discriminate the two
                # common containers.
                elif len(body) > 12 and body[4:8] == b"ftyp":
                    sub = body[8:12]
                    if   sub == b"qt  ":                   ext = ".mov"
                    elif sub.startswith(b"M4V"):           ext = ".m4v"
                    else:                                  ext = ".mp4"
                if ext is None:
                    http_error(writer, 400, "unsupported file format (need PNG / JPEG / WebP / GIF / MP4 / WebM / MOV)")
                    try: await writer.drain()
                    except Exception: pass
                    try: writer.close()
                    except Exception: pass
                    return
                slug = _library_slug(label, library_dir())
                fp = library_dir() / (slug + ext)
                fp.write_bytes(body)
                # v2.2.0-beta hotfix: optional Luminance-Alpha auto-cut
                # + the catalogue rebuild that follows are CPU-heavy
                # and used to run synchronously inside this async
                # handler — a 4K upload would freeze the whole bridge
                # for ~30-60 s while the event loop blocked. Push both
                # into the default executor so other Configurator /
                # WebSocket / wallpaper requests keep flowing. Also
                # drop WebP method=6 → 4: ~5× faster at near-identical
                # quality for wallpapers.
                want_autocut = (params.get("autocut") == "1"
                        and ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp"))
                def _post_upload_work(initial_fp, do_autocut, slug_name):
                    final_fp = initial_fp
                    if do_autocut:
                        try:
                            im = Image.open(initial_fp).convert("RGB")
                            gray = im.convert("L")
                            # alpha = 255 − lum so bright pixels go
                            # transparent. Linear curve, no thresholds.
                            alpha = gray.point(lambda v: 255 - v)
                            rgba = im.convert("RGBA")
                            rgba.putalpha(alpha)
                            # Always WebP-encode the auto-cut output so the
                            # alpha channel is honoured by the catalogue.
                            initial_fp.unlink(missing_ok=True)
                            final_fp = library_dir() / (slug_name + ".webp")
                            rgba.save(final_fp, format="WebP",
                                      quality=88, method=4)
                        except Exception as e:
                            print(f"[upload-autocut] {slug_name}: {e}")
                    _library_rebuild_catalogue(library_dir())
                    return final_fp
                loop = asyncio.get_event_loop()
                fp = await loop.run_in_executor(
                    None, _post_upload_work, fp, want_autocut, slug)
                # Apply the uploader-specified category to the
                # freshly-catalogued entry. Done AFTER rebuild so the
                # entry exists in library.json.
                if upload_category != "both":
                    _library_update_item(
                        library_dir(), fp.name,
                        lambda it, c=upload_category: it.update({"category": c})
                    )
                payload = json.dumps({"ok": True, "id": slug, "file": fp.name}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 500, f"upload failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_library_delete(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # DELETE /library/<name> — removes the file + its thumbnail (if any)
        # + regenerates library.json. Same path-traversal protections as the
        # GET handler. We only delete inside library_dir(); no risk of
        # walking out via dots or separators.
        if method == "DELETE" and target.split("?", 1)[0].startswith("/library/"):
            # v2.2.2 hardening: match the GET handler's filename
            # validation. The pre-2.2.2 DELETE path was missing three
            # things the GET path already had: URL-decoding (so
            # `DELETE /library/some%20file.png` 404'd instead of
            # working), the leading-dot rejection (`.hiddenfile` was
            # deletable), and the resolve().relative_to() symlink-
            # escape check.
            raw = target.split("?", 1)[0][len("/library/"):]
            try:
                name = urllib.parse.unquote(raw)
            except Exception:
                name = raw
            if (not name
                    or "/" in name or "\\" in name or ".." in name
                    or name.startswith(".")):
                http_error(writer, 400, "bad library filename")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                lib_root = library_dir().resolve()
                fp_resolved = (lib_root / name).resolve()
                try:
                    fp_resolved.relative_to(lib_root)
                except ValueError:
                    http_error(writer, 400, "library path escapes root")
                    try: await writer.drain()
                    except Exception: pass
                    try: writer.close()
                    except Exception: pass
                    return
                lib = library_dir()
                fp = lib / name
                if fp.exists() and fp.is_file():
                    fp.unlink()
                # Also drop a sibling .thumb.png if present (matches our
                # generator's naming) — try both <name>.thumb.png and
                # <stem>.thumb.png since the file extension might differ.
                stem = fp.stem
                if stem.endswith(".thumb"): stem = stem[:-len(".thumb")]
                for cand in (lib / (stem + ".thumb.png"), lib / (fp.name + ".thumb")):
                    try:
                        if cand.exists(): cand.unlink()
                    except Exception: pass
                # v2.2.2: catalogue rebuild moved to executor — see the
                # v2.2.1 autocut / transform fix for the same rationale.
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, _library_rebuild_catalogue, lib)
                payload = b'{"ok":true}'
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"delete failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_library_pin(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # POST /library/pin — body is JSON {"file": "...", "pinned": bool}.
        # Toggles the pin flag on a library entry without re-scanning the
        # directory; the Configurator's right-click Pin/Unpin menu hits
        # this. Returns the updated entry.
        if method == "POST" and target.split("?", 1)[0] == "/library/pin":
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= 8192):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                req = json.loads(body.decode("utf-8"))
                file = str(req.get("file", ""))
                pinned = bool(req.get("pinned", False))
                if not file or "/" in file or "\\" in file or ".." in file:
                    http_error(writer, 400, "bad file name")
                    try: await writer.drain()
                    except Exception: pass
                    try: writer.close()
                    except Exception: pass
                    return
                updated = _library_update_item(
                    library_dir(), file, lambda it: it.update({"pinned": pinned})
                )
                if updated is None:
                    http_error(writer, 404, f"library entry not found: {file}")
                else:
                    payload = json.dumps({"ok": True, "item": updated}).encode("utf-8")
                    head = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(payload)}\r\n"
                        "Cache-Control: no-store\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode()
                    writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 500, f"pin failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_library_category(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v1.6.1-beta: POST /library/category — body is JSON
        # {"file": "...", "category": "background"|"template"|"both"}.
        # Configurator's library tile context-menu writes this when
        # the user changes an item's role. Sanity-checked the same
        # way pin/reorder are.
        if method == "POST" and target.split("?", 1)[0] == "/library/category":
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= 8192):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                req = json.loads(body.decode("utf-8"))
                file = str(req.get("file", ""))
                cat = str(req.get("category", "both"))
                if cat not in ("background", "template", "both"):
                    cat = "both"
                if not file or "/" in file or "\\" in file or ".." in file:
                    http_error(writer, 400, "bad file name")
                    try: await writer.drain()
                    except Exception: pass
                    try: writer.close()
                    except Exception: pass
                    return
                updated = _library_update_item(
                    library_dir(), file,
                    lambda it: it.update({"category": cat})
                )
                if updated is None:
                    http_error(writer, 404, f"library entry not found: {file}")
                else:
                    payload = json.dumps({"ok": True, "item": updated}).encode("utf-8")
                    head = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(payload)}\r\n"
                        "Cache-Control: no-store\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode()
                    writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 500, f"category update failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_library_transform(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v2.2.0-beta: POST /library/transform — body is JSON
        # {"file": "...", "op": "rotate90cw|rotate90ccw|rotate180|flipH|flipV"}.
        # In-place rotates / flips the WebP (and its .thumb / .4k
        # siblings if present) via Pillow's transpose primitives —
        # no quality loss because we keep the original colour mode +
        # quality setting. Pinned / category / tag state survive
        # because the file name doesn't change.
        if method == "POST" and target.split("?", 1)[0] == "/library/transform":
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= 1024):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                req = json.loads(body.decode("utf-8"))
                file = str(req.get("file", ""))
                op = str(req.get("op", ""))
                if not file or "/" in file or "\\" in file or ".." in file:
                    raise ValueError("bad file name")
                op_map = {
                    "rotate90cw":  Image.Transpose.ROTATE_270,
                    "rotate90ccw": Image.Transpose.ROTATE_90,
                    "rotate180":   Image.Transpose.ROTATE_180,
                    "flipH":       Image.Transpose.FLIP_LEFT_RIGHT,
                    "flipV":       Image.Transpose.FLIP_TOP_BOTTOM,
                }
                if op not in op_map:
                    raise ValueError(f"unknown op: {op}")
                lib = library_dir()
                fp = lib / file
                if not fp.exists() or not fp.is_file():
                    raise FileNotFoundError(file)
                # Apply the transpose to the main file + any sibling
                # variants the bundled wallpapers carry (thumb + 4K).
                stem = fp.stem
                ext = fp.suffix
                targets = [fp]
                for sib in (lib / f"{stem}.thumb{ext}",
                            lib / f"{stem}.4k{ext}"):
                    if sib.exists():
                        targets.append(sib)
                # v2.2.0-beta hotfix: the PIL transpose + WebP re-
                # encode (×3 variants for bundled wallpapers) used to
                # run synchronously inside this async handler — a 4K
                # bundled WebP at method=6 froze the bridge for tens
                # of seconds and tripped the client-side fetch timeout.
                # Move into the executor and drop method=6 → 4 (~5×
                # faster, near-identical quality).
                def _do_transform(targets_, op_kind):
                    for tgt in targets_:
                        im = Image.open(tgt)
                        mode = im.mode
                        im2 = im.transpose(op_kind)
                        save_kwargs = {}
                        if tgt.suffix.lower() == ".webp":
                            save_kwargs["quality"] = 88
                            save_kwargs["method"] = 4
                        im2.save(tgt, **save_kwargs)
                    # Refreshing the catalogue updates mtime fields
                    # the configurator uses for cache-buster URL
                    # parameters.
                    _library_rebuild_catalogue(lib)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, _do_transform, targets, op_map[op])
                payload = json.dumps({"ok": True}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 400, f"transform failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_library_openfolder(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v2.2.0-beta: POST /library/openfolder — opens the user's
        # library directory in Explorer. Tray menu + Library-tab hint
        # both call this. Pure os.startfile, no payload needed.
        if method == "POST" and target.split("?", 1)[0] == "/library/openfolder":
            try:
                lib = library_dir()
                lib.mkdir(parents=True, exist_ok=True)
                try:
                    os.startfile(str(lib))   # type: ignore[attr-defined]
                except AttributeError:
                    # Non-Windows dev fallback — bridge always runs on
                    # Windows in production, but keep the dev path alive.
                    pass
                payload = json.dumps({"ok": True,
                                      "path": str(lib)}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 500, f"open failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_packs_list(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v2.3.0-beta: GET /packs/list — proxies the discovery manifest
        # at https://delido.github.io/signalrgb-wallpaper/library-packs.json
        # so the Configurator's pack browser can list available
        # downloadable wallpaper packs. Pre-2.0.1 this endpoint hit
        # raw.githubusercontent.com directly; 2.3.0-beta moves it to
        # the GitHub Pages host because Pages traffic looks like
        # normal docs traffic to AV / firewall heuristics, while raw.
        # GHUserContent traffic is more often classified as binary
        # download. The manifest itself is plain JSON either way.
        if method == "GET" and target.split("?", 1)[0] == "/packs/list":
            try:
                loop = asyncio.get_event_loop()
                manifest_json = await loop.run_in_executor(
                    None, _packs_fetch_manifest)
                # Annotate each pack with "installed" + "installed_version"
                # so the UI can show "Update available" without a second
                # round-trip. Reads library.json directly.
                installed = _packs_installed_state(library_dir())
                try:
                    manifest = json.loads(manifest_json)
                except Exception:
                    manifest = {"schema": 1, "packs": []}
                for p in manifest.get("packs", []):
                    if not isinstance(p, dict):
                        continue
                    inst = installed.get(p.get("id"), 0)
                    p["installed_version"] = inst
                    p["installed"] = inst > 0
                payload = json.dumps(manifest).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except Exception as e:
                http_error(writer, 502, f"manifest fetch failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_packs_install(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v2.3.0-beta: POST /packs/install — body is JSON
        # {"pack_id": "...", "url": "...", "sha256": "...",
        #  "size_bytes": ..., "pack_version": ...}.
        # Downloads the ZIP, verifies SHA-256 against the supplied
        # digest, validates every entry is an image (no .exe / .dll /
        # .bat / .ps1 / etc. — defence in depth against a malicious
        # pack mid-stream), extracts the images into
        # %LOCALAPPDATA%\SignalRGBWallpaper\library\, then triggers
        # a catalogue rebuild. Long-running, runs entirely in the
        # executor so the event loop keeps serving other requests.
        if method == "POST" and target.split("?", 1)[0] == "/packs/install":
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= 4096):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                req = json.loads(body.decode("utf-8"))
                pack_id    = str(req.get("pack_id", "")).strip()
                pack_url   = str(req.get("url", "")).strip()
                pack_sha   = str(req.get("sha256", "")).strip().lower()
                pack_size  = int(req.get("size_bytes", 0))
                pack_ver   = int(req.get("pack_version", 1))
                # Lightweight input validation — the bridge talks
                # to a same-host trusted UI, but the manifest is
                # fetched from the public internet so we don't want
                # to follow an arbitrary URL or write to a
                # path-traversal-shaped pack_id either.
                if (not pack_id or not pack_url or not pack_sha
                        or "/" in pack_id or "\\" in pack_id
                        or ".." in pack_id
                        or len(pack_sha) != 64
                        or not pack_url.startswith("https://github.com/")):
                    raise ValueError("invalid pack descriptor")
                loop = asyncio.get_event_loop()
                report = await loop.run_in_executor(
                    None, _packs_install,
                    pack_id, pack_url, pack_sha, pack_size, pack_ver)
                payload = json.dumps({"ok": True, **report}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 400, f"pack install failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_packs_uninstall(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v2.3.0-beta.1: POST /packs/uninstall — body is JSON
        # {"pack_id": "..."}. Walks library.json, removes every
        # file (+ siblings: .thumb.*, .4k.*) whose entry carries
        # pack == pack_id, then rebuilds the catalogue. User-
        # uploaded items without a pack stamp are never touched.
        # Runs in the executor.
        if method == "POST" and target.split("?", 1)[0] == "/packs/uninstall":
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= 256):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                req = json.loads(body.decode("utf-8"))
                pack_id = str(req.get("pack_id", "")).strip()
                if (not pack_id or "/" in pack_id or "\\" in pack_id
                        or ".." in pack_id):
                    raise ValueError("invalid pack_id")
                loop = asyncio.get_event_loop()
                report = await loop.run_in_executor(
                    None, _packs_uninstall, pack_id)
                payload = json.dumps({"ok": True, **report}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 400, f"pack uninstall failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_library_tags(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v1.7.5: POST /library/tags — body is JSON
        # {"file": "...", "tags": ["cyberpunk", "neon", ...]}. Mirrors
        # the /library/category and /library/pin patterns. Tags get
        # length-capped (32 chars each) + count-capped (24 per item)
        # so a runaway client can't bloat library.json.
        if method == "POST" and target.split("?", 1)[0] == "/library/tags":
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= 8192):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                req = json.loads(body.decode("utf-8"))
                file = str(req.get("file", ""))
                raw_tags = req.get("tags") or []
                if not isinstance(raw_tags, list):
                    raw_tags = []
                # Normalise: trim, lowercase, dedup, cap length + count.
                seen: set[str] = set()
                tags: list[str] = []
                for tg in raw_tags:
                    if not isinstance(tg, str):
                        continue
                    norm = tg.strip().lower()[:32]
                    if norm and norm not in seen:
                        seen.add(norm)
                        tags.append(norm)
                        if len(tags) >= 24:
                            break
                if not file or "/" in file or "\\" in file or ".." in file:
                    http_error(writer, 400, "bad file name")
                    try: await writer.drain()
                    except Exception: pass
                    try: writer.close()
                    except Exception: pass
                    return
                def _apply_tags(it, _tags=tags):
                    if _tags:
                        it["tags"] = _tags
                    else:
                        # Empty list = remove the field entirely. Cleaner
                        # library.json + matches "no tag info" semantics.
                        it.pop("tags", None)
                updated = _library_update_item(
                    library_dir(), file, _apply_tags
                )
                if updated is None:
                    http_error(writer, 404, f"library entry not found: {file}")
                else:
                    payload = json.dumps({"ok": True, "item": updated}).encode("utf-8")
                    head = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(payload)}\r\n"
                        "Cache-Control: no-store\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode()
                    writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 500, f"tags update failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_library_reorder(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # POST /library/reorder — body is JSON {"order": ["a.png", "b.png", ...]}.
        # Assigns sequential `order` indices to matching entries. The
        # Configurator drags-and-drops tiles in the Library strip and
        # POSTs the new order here.
        if method == "POST" and target.split("?", 1)[0] == "/library/reorder":
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= 65536):
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                req = json.loads(body.decode("utf-8"))
                raw_order = req.get("order", [])
                if not isinstance(raw_order, list):
                    raise ValueError("`order` must be a list")
                order = []
                for f in raw_order:
                    s = str(f)
                    if not s or "/" in s or "\\" in s or ".." in s:
                        raise ValueError(f"bad file name in order: {s!r}")
                    order.append(s)
                n = _library_apply_order(library_dir(), order)
                payload = json.dumps({"ok": True, "applied": n}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except Exception as e:
                http_error(writer, 500, f"reorder failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_backup(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # GET /backup — stream a ZIP of every piece of user state
        # (config.json + library/ + screens/). Browser-driven download.
        if method == "GET" and target.split("?", 1)[0] == "/backup":
            try:
                bridge_runtime = getattr(self, "bridge_runtime", None) or self
                data = bridge_runtime.build_backup_zip()
                stamp = time.strftime("%Y%m%d-%H%M%S")
                filename = f"signalrgb-wallpaper-backup-{stamp}.zip"
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/zip\r\n"
                    f"Content-Length: {len(data)}\r\n"
                    f"Content-Disposition: attachment; filename=\"{filename}\"\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + data)
            except Exception as e:
                http_error(writer, 500, f"backup failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_restore(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # POST /restore — body is the raw ZIP. Replaces config.json,
        # merges library/ + screens/ files on top of the existing dirs,
        # then pushes fresh settings to every connected wallpaper page.
        if method == "POST" and target.split("?", 1)[0] == "/restore":
            try:
                content_length = int(headers.get(b"content-length", b"0") or 0)
            except ValueError:
                content_length = 0
            if not (0 < content_length <= 100 * 1024 * 1024):  # 100 MB cap
                http_error(writer, 400, f"bad content-length: {content_length}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                body = await reader.readexactly(content_length)
                bridge_runtime = getattr(self, "bridge_runtime", None) or self
                # v2.2.2: ZIP extraction + per-file writes + library
                # rebuild used to run on the event loop. A 100 MB
                # backup restore froze the bridge for 5-30 s; every
                # WS ping / Configurator request stalled. Push the
                # whole thing into the default executor.
                loop = asyncio.get_event_loop()
                report = await loop.run_in_executor(
                    None, bridge_runtime.restore_backup_zip, body)
                payload = json.dumps({"ok": True, **report}).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + payload)
            except asyncio.IncompleteReadError:
                http_error(writer, 400, "incomplete body")
            except ValueError as e:
                http_error(writer, 400, f"restore rejected: {e}")
            except Exception as e:
                http_error(writer, 500, f"restore failed: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_help(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # In-browser help page — scenario-based walkthroughs (1/2/3/4
        # monitors × Lively / Wallpaper Engine). Static HTML; pulls the
        # active language from /config like the Builder does. Images
        # under /help/images/* served from a sibling folder so the
        # maintainer can drop screenshots in by hand.
        if method == "GET" and target.split("?", 1)[0] in ("/help", "/help/"):
            try:
                help_path = _resource_path("help.html")
                data = help_path.read_bytes()
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    f"Content-Length: {len(data)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + data)
            except FileNotFoundError:
                http_error(writer, 500, "help.html not bundled with this build")
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_help_images(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""
        # /help/images/<file> — optional screenshots the maintainer can
        # drop into wallpaper_bridge/help_assets/ (dev) or
        # %LOCALAPPDATA%\SignalRGBWallpaper\help_images\ (post-install).
        # Path-traversal protected like /library.
        if method == "GET" and target.split("?", 1)[0].startswith("/help/images/"):
            name = target.split("?", 1)[0][len("/help/images/"):]
            if not name or "/" in name or "\\" in name or ".." in name:
                http_error(writer, 400, "bad help-image filename")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return
            try:
                # Prefer the user-writable %LOCALAPPDATA% copy so users can
                # add their own screenshots without rebuilding the bridge.
                user_dir = config_path().parent / "help_images"
                dev_dir  = Path(__file__).resolve().parent / "help_assets"
                fp = None
                for cand in (user_dir / name, dev_dir / name):
                    if cand.exists() and cand.is_file():
                        fp = cand; break
                if fp is None:
                    http_error(writer, 404, "help image not found")
                else:
                    body = fp.read_bytes()
                    ct, _ = mimetypes.guess_type(str(fp))
                    if not ct: ct = "application/octet-stream"
                    head = (
                        "HTTP/1.1 200 OK\r\n"
                        f"Content-Type: {ct}\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        "Cache-Control: public, max-age=86400\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode()
                    writer.write(head + body)
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_configurator(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # In-browser configurator — replaces the tray's per-screen widget /
        # effect submenus with a rich tabbed UI. Same WS protocol as the
        # wallpaper page; sends `setting-update` / `widget-*` commands.
        if method == "GET" and target.split("?", 1)[0] in ("/configurator", "/configurator/"):
            try:
                cfg_path = _resource_path("configurator.html")
                data = cfg_path.read_bytes()
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    f"Content-Length: {len(data)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode()
                writer.write(head + data)
            except FileNotFoundError:
                http_error(writer, 500, "configurator.html not bundled with this build")
            except Exception as e:
                http_error(writer, 500, f"server error: {e}")
            try: await writer.drain()
            except Exception: pass
            try: writer.close()
            except Exception: pass
            return

    async def _route_wallpaper_assets(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # ── /wallpaper (live-preview path, v1.2-dev) ──
        # Serves wallpaper/index.html + its sibling assets from inside
        # the bridge so the Configurator can embed the actual wallpaper
        # page as an iframe (live edit-see-result instead of the
        # schematic drag-area we had before). Lively / WE keep loading
        # the wallpaper from their own extracted copies — this route
        # only exists for in-browser preview.
        if method == "GET":
            tgt = target.split("?", 1)[0]
            if tgt in ("/wallpaper", "/wallpaper/"):
                tgt = "/wallpaper/index.html"
            if tgt.startswith("/wallpaper/"):
                rel = tgt[len("/wallpaper/"):]
                # Reject any path-traversal attempts. Allow only ASCII
                # word chars + dot + slash + dash so we don't accidentally
                # become a file-system browser.
                if ".." in rel or not all(c.isalnum() or c in "._/-" for c in rel):
                    http_error(writer, 400, "bad path")
                else:
                    try:
                        asset = _resource_path("wallpaper") / rel
                        if not asset.is_file():
                            http_error(writer, 404, "not found")
                        else:
                            ctype = mimetypes.guess_type(str(asset))[0] or "application/octet-stream"
                            data = asset.read_bytes()
                            # Text-ish payloads get a charset so the
                            # browser doesn't second-guess; binary
                            # (images, fonts) just gets the bare type.
                            is_text = (ctype.startswith("text/")
                                       or ctype.endswith("/json")
                                       or ctype.endswith("/javascript")
                                       or ctype.endswith("/xml"))
                            ctype_h = f"{ctype}; charset=utf-8" if is_text else ctype
                            head = (
                                "HTTP/1.1 200 OK\r\n"
                                f"Content-Type: {ctype_h}\r\n"
                                f"Content-Length: {len(data)}\r\n"
                                "Cache-Control: no-store\r\n"
                                "Connection: close\r\n\r\n"
                            )
                            writer.write(head.encode() + data)
                    except Exception as e:
                        http_error(writer, 500, f"server error: {e}")
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return

    async def _route_plugins(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v1.5.0-beta plugin API: serve plugin assets under
        # /plugins/<name>/<rel>. The PluginRegistry's resolve_asset
        # refuses anything that escapes the plugin's own folder.
        # Files are served with a strict CSP so a plugin can't
        # exfiltrate to arbitrary origins via fetch / XHR. The
        # sandbox attribute on the iframe in the wallpaper page is
        # the primary isolation; CSP is belt + braces.
        if (method == "GET"
                and target.split("?", 1)[0].startswith("/plugins/")):
            parts = target.split("?", 1)[0].split("/")
            # ["", "plugins", "<name>", *rest]
            if len(parts) >= 4 and parts[2]:
                plug_name = parts[2]
                rel = "/".join(parts[3:]) or "widget.html"
                reg = getattr(self, "plugin_registry", None)
                if reg is None:
                    http_error(writer, 503,
                               "plugin registry not wired",
                               request_headers=headers)
                else:
                    asset = reg.resolve_asset(plug_name, rel)
                    if asset is None:
                        http_error(writer, 404, "plugin asset not found",
                                   request_headers=headers)
                    else:
                        try:
                            data = asset.read_bytes()
                            ctype = (mimetypes.guess_type(str(asset))[0]
                                     or "application/octet-stream")
                            head_b = (
                                "HTTP/1.1 200 OK\r\n"
                                f"Content-Type: {ctype}\r\n"
                                f"Content-Length: {len(data)}\r\n"
                                "Cache-Control: no-store\r\n"
                                "Content-Security-Policy: "
                                "default-src 'self' 'unsafe-inline'; "
                                "img-src 'self' data:; "
                                "connect-src 'self'\r\n"
                                f"Access-Control-Allow-Origin: {_acao(headers)}\r\n"
                                "Connection: close\r\n\r\n"
                            ).encode()
                            writer.write(head_b + data)
                        except Exception as e:
                            http_error(writer, 500,
                                       f"plugin asset read failed: {e}",
                                       request_headers=headers)
                try: await writer.drain()
                except Exception: pass
                try: writer.close()
                except Exception: pass
                return

    async def _route_api_openapi_json(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""

        # v1.5.0-beta: REST API + OpenAPI. All /api/v1/* routes go
        # through `_handle_api_request` which enforces token auth on
        # non-loopback requests (loopback bypasses so the local
        # Configurator + same-host HA work without configuration).
        # /api/openapi.json is served public so clients can fetch the
        # spec without auth.
        clean_target = target.split("?", 1)[0]
        if clean_target == "/api/openapi.json":
            await self._serve_openapi_spec(writer, headers)
            return

    async def _route_api_v1(self, method, target, headers, reader, writer):
        """Split out of handle_client. Answers the request and
        closes the writer, or leaves it open for the next route."""
        clean_target = target.split("?", 1)[0]
        if clean_target.startswith("/api/v1/"):
            # Pull the request body when present — the handler picks
            # the routes that actually need it.
            body = b""
            try:
                content_length = int(headers.get("content-length") or "0")
            except ValueError:
                content_length = 0
            if content_length > 0 and content_length < 1_048_576:
                try:
                    body = await reader.readexactly(content_length)
                except Exception:
                    body = b""
            await self._handle_api_request(reader, writer, method,
                                            clean_target, target,
                                            headers, body)
            return

    # ── v1.5.0-beta REST API ────────────────────────────────────────────

    def _is_loopback_request(self, writer) -> bool:
        """True iff the request arrived over a 127.0.0.1 / ::1 socket.
        WS_HOST is currently bound to 127.0.0.1 so this is always
        True today; kept as a separate helper so a future LAN-binding
        opt-in still has the right gate available."""
        try:
            peer = writer.get_extra_info("peername")
            if peer is None:
                return True
            host = str(peer[0])
            return host in ("127.0.0.1", "::1", "0:0:0:0:0:0:0:1")
        except Exception:
            return True

    def _check_api_auth(self, writer, headers: dict) -> bool:
        """Loopback requests bypass; remote requests need a valid
        `Authorization: Bearer <apiToken>` header. The token lives
        under `config.apiToken` and is auto-generated on first run."""
        if self._is_loopback_request(writer):
            return True
        runtime = getattr(self, "bridge_runtime", None)
        if runtime is None:
            return False
        expected = ""
        try:
            with runtime.config_lock:
                expected = str(runtime.config.get("apiToken") or "")
        except Exception:
            return False
        if not expected:
            return False
        auth = (headers.get("authorization") or "").strip()
        if not auth.lower().startswith("bearer "):
            return False
        return auth.split(" ", 1)[1].strip() == expected

    async def _send_json(self, writer, headers: dict,
                        status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        head = (
            f"HTTP/1.1 {status} {'OK' if 200 <= status < 300 else 'Error'}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            f"Access-Control-Allow-Origin: {_acao(headers)}\r\n"
            "Access-Control-Allow-Headers: Authorization, Content-Type\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
        writer.write(head + body)
        try: await writer.drain()
        except Exception: pass
        try: writer.close()
        except Exception: pass

    async def _serve_openapi_spec(self, writer, headers: dict) -> None:
        """Minimal OpenAPI 3.1 surface for the v1 endpoints. Hand-
        written rather than introspected so it stays accurate when
        endpoints change — the surface is small enough to maintain
        manually + a generated spec would mean depending on FastAPI
        or similar, neither of which we ship."""
        spec = {
            "openapi": "3.1.0",
            "info": {
                "title": "SignalRGB Wallpaper Bridge API",
                "version": "1",
                "description": (
                    "Local-only HTTP API exposed by the SignalRGB "
                    "Wallpaper Bridge on 127.0.0.1:17320. All "
                    "endpoints under /api/v1 require an "
                    "`Authorization: Bearer <apiToken>` header "
                    "when accessed over a non-loopback socket; "
                    "loopback bypasses auth so the Configurator + "
                    "same-host integrations work out of the box. "
                    "The token lives under config.apiToken and is "
                    "shown / regenerable from the Configurator's "
                    "System card."
                ),
            },
            "servers": [{"url": f"http://{WS_HOST}:{WS_PORT}"}],
            "components": {
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                    },
                },
            },
            "security": [{"bearerAuth": []}],
            "paths": {
                "/api/v1/info": {
                    "get": {
                        "summary": "Bridge version + capabilities",
                        "responses": {"200": {"description": "OK"}},
                    },
                },
                "/api/v1/auth/verify": {
                    "post": {
                        "summary": "Verify the supplied token works",
                        "responses": {
                            "200": {"description": "Authorised"},
                            "401": {"description": "Bad / missing token"},
                        },
                    },
                },
                "/api/v1/screens": {
                    "get": {
                        "summary": "List all bridge screens with summary",
                        "responses": {"200": {"description": "OK"}},
                    },
                },
                "/api/v1/screens/{n}/settings": {
                    "get": {
                        "summary": "Read per-screen settings",
                        "parameters": [
                            {"name": "n", "in": "path", "required": True,
                             "schema": {"type": "integer",
                                        "minimum": 0,
                                        "maximum": N_SCREENS - 1}},
                        ],
                        "responses": {"200": {"description": "OK"}},
                    },
                },
                "/api/v1/screens/{n}/preset/{slot}/apply": {
                    "post": {
                        "summary": "Apply preset slot to a screen",
                        "parameters": [
                            {"name": "n", "in": "path", "required": True,
                             "schema": {"type": "integer"}},
                            {"name": "slot", "in": "path", "required": True,
                             "schema": {"type": "integer", "minimum": 0,
                                        "maximum": PRESET_SLOTS - 1}},
                        ],
                        "responses": {
                            "200": {"description": "Applied"},
                            "404": {"description": "Screen / slot invalid"},
                        },
                    },
                },
                "/api/v1/screens/{n}/pause": {
                    "post": {
                        "summary": "Set manual pause state for the bridge",
                        "requestBody": {
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {
                                    "paused": {"type": "boolean"},
                                },
                            }}},
                        },
                        "responses": {"200": {"description": "OK"}},
                    },
                },
                "/api/v1/profiles": {
                    "get": {"summary": "List per-app profile rules"},
                },
                "/api/v1/plugins": {
                    "get": {
                        "summary": "List third-party widget plugins discovered "
                                   "in %LOCALAPPDATA%\\SignalRGBWallpaper\\plugins\\",
                    },
                },
            },
        }
        await self._send_json(writer, headers, 200, spec)

    async def _handle_api_request(self, reader, writer,
                                    method: str, route: str,
                                    target_raw: str,
                                    headers: dict, body: bytes) -> None:
        """Dispatch /api/v1/* requests. Keeps each route tiny so
        future additions / removals stay self-contained."""
        if not self._check_api_auth(writer, headers):
            await self._send_json(writer, headers, 401, {
                "error": "auth required",
                "hint": "send `Authorization: Bearer <apiToken>` "
                        "(token is shown in the Configurator's "
                        "System card)",
            })
            return
        runtime = getattr(self, "bridge_runtime", None)
        if runtime is None:
            await self._send_json(writer, headers, 503, {
                "error": "bridge runtime not wired",
            })
            return

        # GET /api/v1/info
        if method == "GET" and route == "/api/v1/info":
            await self._send_json(writer, headers, 200, {
                "appVersion":       APP_VERSION,
                "wallpaperVersion": WALLPAPER_VERSION,
                "screenCount":      int(self.get_screen_count()),
                "maxScreens":       N_SCREENS,
                "presetSlots":      PRESET_SLOTS,
                "capabilities":     [
                    "presets", "profiles", "openrgbOutput",
                    "openrgbInput", "sacnOutput", "sacnInput",
                    "spatialMapping", "mqttBridge", "plugins",
                ],
            })
            return

        # POST /api/v1/auth/verify
        if method == "POST" and route == "/api/v1/auth/verify":
            await self._send_json(writer, headers, 200, {"ok": True})
            return

        # GET /api/v1/screens
        if method == "GET" and route == "/api/v1/screens":
            sc = int(self.get_screen_count())
            screens = []
            for n in range(N_SCREENS):
                try:
                    s = self.get_settings(n)
                    screens.append({
                        "index":    n,
                        "active":   n < sc,
                        "viewportW": s.get("viewportW"),
                        "viewportH": s.get("viewportH"),
                        "mirrorOf":  s.get("mirrorOf"),
                        "bgImage":   s.get("bgImage"),
                    })
                except Exception:
                    screens.append({"index": n, "active": n < sc})
            await self._send_json(writer, headers, 200, {"screens": screens})
            return

        # GET /api/v1/screens/<n>/settings
        m = re.match(r"^/api/v1/screens/(\d+)/settings$", route)
        if m and method == "GET":
            n = int(m.group(1))
            if not 0 <= n < N_SCREENS:
                await self._send_json(writer, headers, 404,
                                       {"error": "screen out of range"})
                return
            try:
                await self._send_json(writer, headers, 200,
                                       self.get_settings(n))
            except Exception as e:
                await self._send_json(writer, headers, 500,
                                       {"error": str(e)})
            return

        # POST /api/v1/screens/<n>/preset/<slot>/apply
        m = re.match(r"^/api/v1/screens/(\d+)/preset/(\d+)/apply$", route)
        if m and method == "POST":
            n = int(m.group(1)); slot = int(m.group(2))
            if not 0 <= n < N_SCREENS:
                await self._send_json(writer, headers, 404,
                                       {"error": "screen out of range"})
                return
            if not 0 <= slot < PRESET_SLOTS:
                await self._send_json(writer, headers, 404,
                                       {"error": "slot out of range"})
                return
            try:
                result = runtime.apply_preset(n, slot)
                if result is None:
                    await self._send_json(writer, headers, 409, {
                        "error": "preset slot empty / screen mirrored",
                    })
                else:
                    await self._send_json(writer, headers, 200,
                                           {"ok": True})
            except Exception as e:
                await self._send_json(writer, headers, 500,
                                       {"error": str(e)})
            return

        # POST /api/v1/screens/<n>/pause   { "paused": bool }
        m = re.match(r"^/api/v1/screens/(\d+)/pause$", route)
        if m and method == "POST":
            try:
                payload = json.loads(body or b"{}")
            except Exception:
                payload = {}
            paused = bool(payload.get("paused", True))
            try:
                runtime.set_manual_pause(paused)
                await self._send_json(writer, headers, 200,
                                       {"paused": paused})
            except Exception as e:
                await self._send_json(writer, headers, 500,
                                       {"error": str(e)})
            return

        # GET /api/v1/profiles
        if method == "GET" and route == "/api/v1/profiles":
            try:
                with runtime.config_lock:
                    profiles = copy.deepcopy(runtime.config.get("profiles") or [])
                await self._send_json(writer, headers, 200,
                                       {"profiles": profiles})
            except Exception as e:
                await self._send_json(writer, headers, 500,
                                       {"error": str(e)})
            return

        # GET /api/v1/sacn/discovered — list senders + their universes
        if method == "GET" and route == "/api/v1/sacn/discovered":
            provider = getattr(self, "sacn_input_provider", None)
            if provider is None:
                await self._send_json(writer, headers, 200,
                                       {"senders": []})
                return
            try:
                await self._send_json(writer, headers, 200,
                                       {"senders": provider.get_discovered()})
            except Exception as e:
                await self._send_json(writer, headers, 500,
                                       {"error": str(e)})
            return

        # GET /api/v1/plugins  — defined by PluginRegistry below
        if method == "GET" and route == "/api/v1/plugins":
            reg = getattr(self, "plugin_provider", None)
            if reg is None:
                await self._send_json(writer, headers, 200,
                                       {"plugins": []})
                return
            try:
                await self._send_json(writer, headers, 200,
                                       {"plugins": reg.list_plugins()})
            except Exception as e:
                await self._send_json(writer, headers, 500,
                                       {"error": str(e)})
            return

        # CORS preflight for the entire API surface
        if method == "OPTIONS" and route.startswith("/api/v1/"):
            await self._send_json(writer, headers, 200, {})
            return

        await self._send_json(writer, headers, 404,
                               {"error": "unknown route",
                                "route": route, "method": method})

    async def _on_hello(self, writer, screen: int, msg: dict):
        """v1.2.12: respond to the wallpaper page's hello handshake.
        The page reports the version baked into its bundle (the
        installer stamps `__WALLPAPER_VERSION__` into the index.html
        meta tag at build time).

        v1.5.0-beta: compare against WALLPAPER_VERSION (the wallpaper-
        bundle code's version), NOT APP_VERSION (the bridge's version).
        A bridge-only release like v1.4 / v1.5 doesn't change wallpaper
        code, so a Lively / WE bundle still stamped with the last
        wallpaper-touching release (1.3.0 today) is correct and must
        not raise the "out of date" banner. Only when WALLPAPER_VERSION
        actually bumps — which implies a Workshop re-upload + Lively
        re-import — should older bundles light up the banner.

        The "dev" sentinel from an un-stamped page short-circuits the
        check entirely — local dev trees are allowed to drift."""
        try:
            wv = str(msg.get("wallpaperVersion") or "").strip()
        except Exception:
            wv = ""
        if not wv or wv == "dev":
            return
        try:
            target_t = _parse_version(WALLPAPER_VERSION)
            wp_t = _parse_version(wv)
        except Exception:
            return
        if wp_t >= target_t:
            return
        # Older bundle → push the mismatch on the same writer.
        payload = {
            "type":      "version-mismatch",
            # "bridge" key kept for back-compat with v1.2.12+ wallpaper
            # pages that already render this banner; carries the
            # WALLPAPER_VERSION the page should be at, not APP_VERSION.
            "bridge":    WALLPAPER_VERSION,
            "wallpaper": wv,
        }
        try:
            frame = encode_text_frame(json.dumps(payload))
            writer.write(frame)
            print(f"[ws] wallpaper version mismatch on screen={screen}: "
                  f"expected={WALLPAPER_VERSION}  bundle={wv}")
        except Exception as e:
            print(f"[ws] version-mismatch push failed: {e}")

    async def _serve_websocket(self, reader, writer, request, target):
        # v1.2.13: WS Origin check. Browsers send the page's Origin on
        # the WS handshake; we reject anything not in the allowlist.
        # Without this, a malicious local script the user accidentally
        # loaded (browser tab, mail-client preview, etc.) could open
        # ws://127.0.0.1:17320/?screen=0 and start dispatching
        # `setting-update` / `widget-add` / `system-action` messages
        # against the bridge. Lively / WE WebView2 pages send
        # `Origin: null` (file://-style), which is whitelisted.
        # Tools that connect without an Origin at all (curl, custom
        # plugins, the SignalRGB plugin itself if it ever grows a WS
        # client) keep working — the check is opt-in to refusal.
        try:
            req_headers = parse_http_headers(request)
            origin = req_headers.get(b"origin")
            # v1.2.13.X: route through _cors_origin_value so the same
            # pattern fallback (any `*.localhost` host, covers
            # Wallpaper Engine's random-hex WebView2 origin) applies
            # to the WS handshake as well as the HTTP CORS header.
            if origin and not _cors_origin_value(origin):
                try: origin_str = origin.decode("latin-1", "replace").strip()
                except Exception: origin_str = "<binary>"
                print(f"[ws] rejecting WS handshake from disallowed Origin: {origin_str!r}")
                try:
                    writer.write(
                        b"HTTP/1.1 403 Forbidden\r\n"
                        b"Content-Length: 0\r\n"
                        b"Connection: close\r\n\r\n"
                    )
                    await writer.drain()
                except Exception: pass
                writer.close()
                return
        except Exception:
            # If anything fails parsing the Origin we fall through to
            # the existing handshake — better to break gracelessly
            # than to lock out a legit client we didn't anticipate.
            pass
        response = make_handshake(request)
        if not response:
            writer.close()
            return
        writer.write(response)
        await writer.drain()
        screen = parse_query_screen(target)
        role = parse_query_role(target)
        await self.add(writer, screen, role)
        try:
            while not writer.is_closing():
                text = await read_client_text_frame(reader)
                if text is None:    # close / EOF
                    break
                # v2.4.1: ANY inbound frame proves the socket is alive —
                # refresh the keepalive stamp before we decide whether
                # the payload itself is interesting.
                self.note_client_seen(writer)
                if text == PONG_SENTINEL:
                    # Pong to our keepalive ping (or a client ping we
                    # must answer per RFC 6455 — cheap enough to always
                    # reply; browsers ignore an unsolicited pong).
                    try:
                        writer.write(_encode_frame(0xA, b""))
                    except Exception:
                        break
                    continue
                if not text:        # ignored frame type (binary, fragmented)
                    continue
                try:
                    msg = json.loads(text)
                except Exception:
                    continue
                # v1.2.12: hello-handshake. The wallpaper page sends
                # this once on WS connect with its bundle's stamped
                # version. We compare against APP_VERSION and, on
                # mismatch, push a `version-mismatch` JSON straight
                # back on the same writer so the page can light up
                # its "re-import bundle" banner. Handled inline here
                # because handle_client_message doesn't see the
                # writer (and broadcasting back to everyone would
                # be wrong — only the stale page should see it).
                if isinstance(msg, dict) and msg.get("type") == "hello":
                    try:
                        await self._on_hello(writer, screen, msg)
                    except Exception as e:
                        print(f"[ws] hello handler failed: {e}")
                    continue
                # v2.4.11: render-path diagnostics. The page reports
                # once a minute which ripple path it is actually using.
                # Logged rather than answered — this exists so the
                # question "is the leaky SVG fallback running?" can be
                # settled from the user's own log instead of from a
                # devtools console they cannot open on a wallpaper.
                # See the _diag block in wallpaper/index.html for why.
                if isinstance(msg, dict) and msg.get("type") == "diag":
                    try:
                        print(
                            f"[diag] screen={screen} "
                            f"gl={int(msg.get('gl') or 0)} "
                            f"svg={int(msg.get('svg') or 0)} "
                            f"no_gl={int(msg.get('usableFalseNoGl') or 0)} "
                            f"no_img={int(msg.get('usableFalseNoImg') or 0)} "
                            f"ctx_lost={int(msg.get('ctxLost') or 0)} "
                            f"ctx_restored={int(msg.get('ctxRestored') or 0)} "
                            f"heap={int(msg.get('heapMb') or 0)}MB"
                        )
                    except Exception as e:
                        print(f"[diag] malformed report: {e}")
                    continue
                self.handle_client_message(screen, msg)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError):
            pass
        finally:
            await self.remove(writer)


class HwMonPoller:
    """Optionally polls LibreHardwareMonitor's built-in HTTP server
    (default `http://localhost:8085/data.json`) for the full sensor tree
    — CPU / GPU / mainboard temps, fan RPMs, voltages, drive temps and
    power readings that psutil doesn't expose on its own.

    LHM ships with a "Remote Web Server" toggle (Options → Remote Web
    Server) that has to be on for this to work. If the user hasn't
    installed LHM or hasn't enabled the server, we just skip — the rest
    of the sysstats payload still ships, our hardware-sensor widgets
    show `--` placeholders.

    LHM's JSON is a deeply nested {id, Text, Value, Children} tree. We
    flatten it to a `path: value` dict keyed by the slash-separated path
    from the root (e.g. "AMD Ryzen 7 5800X / Temperatures / Core
    (Tctl/Tdie)"), parsing the `Value` field's numeric prefix so the
    wallpaper page can plot it as a sparkline. The original unit
    (°C / RPM / V / W / %) is captured alongside so widgets can label
    correctly without re-guessing.

    License: LibreHardwareMonitor is MPL 2.0 — we don't bundle it, only
    talk to its REST server when the user has it running, so no MPL
    propagation into our MIT distribution.
    """

    DEFAULT_URL = "http://localhost:8085/data.json"
    POLL_INTERVAL_S = 1.0
    REQUEST_TIMEOUT_S = 0.8

    def __init__(self, should_poll=None):
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # v1.2.8: callable()->bool gate. False = skip the HTTP GET to
        # LibreHardwareMonitor; the snapshot from the previous successful
        # poll is kept around for the /hwmon/sensors HTTP endpoint that
        # the Configurator's sensor-picker hits. No-clients means no
        # widget is reading it, so the cost is wasted.
        self._should_poll = should_poll
        # path -> {"value": float, "raw": "45.5 °C", "unit": "°C"}
        self._snapshot: dict[str, dict] = {}
        self._last_ok_ts: float = 0.0
        self._last_error: str = ""
        # Size of the last payload we received from LHM, for the
        # "server reachable but 0 sensors parsed" diagnostic that the
        # Configurator's sensor-picker surfaces in its placeholder
        # option.
        self._last_payload_bytes: int = 0
        # Print a one-time hint when we first see a non-empty payload
        # produce zero sensors — so the bridge log carries a copy of
        # the JSON's root keys for the dev to look at, without
        # spamming the log every poll.
        self._warned_about_empty_parse = False

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="hwmon-poll").start()
        print(f"[hwmon] poller running (target {self.DEFAULT_URL}, "
              f"{self.POLL_INTERVAL_S} Hz). Optional: requires "
              "LibreHardwareMonitor with Remote Web Server enabled.")

    def stop(self):
        self._stop.set()

    def get_snapshot(self) -> dict:
        with self._lock:
            return dict(self._snapshot)

    def get_status(self) -> dict:
        """Tiny status object for the Configurator's 'LHM detected?'
        hint. Reports whether we last reached LHM, how long ago, and a
        sensor count for sanity."""
        with self._lock:
            return {
                "online":     bool(self._last_ok_ts) and
                              (time.time() - self._last_ok_ts) < 5,
                "lastOkTs":   int(self._last_ok_ts * 1000),
                "sensorCount": len(self._snapshot),
                "lastError":  self._last_error,
                "lastPayloadBytes": self._last_payload_bytes,
            }

    def _run(self):
        while not self._stop.is_set():
            # v1.2.8: idle-gate. Skip the HTTP GET when no wallpaper
            # page is connected — the snapshot has no reader.
            try:
                poll = self._should_poll() if self._should_poll else True
            except Exception:
                poll = True
            if not poll:
                if self._stop.wait(self.POLL_INTERVAL_S):
                    return
                continue
            try:
                req = urllib.request.Request(self.DEFAULT_URL,
                                              headers={"User-Agent": "SignalRGBBridge"})
                with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT_S) as resp:
                    payload = resp.read()
                tree = json.loads(payload)
                flat = self._flatten(tree)
                with self._lock:
                    self._snapshot = flat
                    self._last_ok_ts = time.time()
                    self._last_payload_bytes = len(payload)
                    if flat:
                        self._last_error = ""
                    else:
                        # We reached LHM, got a payload, but parsed zero
                        # sensors. Most likely the tree shape is
                        # different from what _flatten walks. Surface it
                        # so the Configurator's sensor-picker tells the
                        # user instead of just listing zero items.
                        self._last_error = "parsed 0 sensors from response"
                        if not self._warned_about_empty_parse:
                            self._warned_about_empty_parse = True
                            try:
                                top_keys = list(tree.keys())[:6]
                                child0 = (tree.get("Children") or [{}])[0]
                                child0_keys = list(child0.keys())[:6]
                                print(f"[hwmon] reachable but parsed 0 sensors from "
                                      f"{len(payload)} B. Root keys: {top_keys}, "
                                      f"first-child keys: {child0_keys}, "
                                      f"first-child Text: {child0.get('Text')!r}")
                            except Exception:
                                print(f"[hwmon] reachable but parsed 0 sensors from "
                                      f"{len(payload)} B (and dumping diagnostics failed)")
            except urllib.error.URLError:
                # Connection refused = LHM server not running. Don't
                # spam the log; just clear the snapshot so widgets show
                # placeholders instead of stale data.
                with self._lock:
                    if self._snapshot:
                        self._snapshot = {}
                    self._last_error = "offline"
            except Exception as e:
                with self._lock:
                    self._last_error = str(e)[:120]
            if self._stop.wait(self.POLL_INTERVAL_S):
                return

    # ── JSON flattening ────────────────────────────────────────────────
    # LHM's tree shape varies by build but the leaves are always
    # nodes with a "Value" string like "45.5 °C" / "1234 RPM" /
    # "0.92 V". The non-leaf wrappers (the outer "Sensor" node, the
    # per-host computer name node, device / category groupings) carry
    # an empty Value (or a non-numeric string like "Min", "Max").
    #
    # Rather than hard-coding the depth we just recurse from the root,
    # treat any node that parses as a number as a sensor, and build
    # paths from one level below the root (so we don't prefix every
    # sensor with "Sensor /"). The "Computer / DESKTOP-…" wrapper
    # stays in the path; with multiple PCs streaming into one LHM
    # instance the per-host prefix is actually useful, and on a
    # single-machine setup it's just one extra segment we accept.
    #
    # Numbers may use comma decimals on de_DE locales — handled by
    # _NUM_RE replacing "," with "." before float().

    _NUM_RE = re.compile(r"^([-+]?\d+(?:[.,]\d+)?)\s*(.*)$")

    @classmethod
    def _flatten(cls, tree: dict) -> dict:
        out: dict[str, dict] = {}
        # Walk every immediate child of the root. The root usually has
        # Text="Sensor"; its children are the per-host computer
        # wrappers. We skip the root's own Text but recurse from one
        # level below so the path doesn't lead with "Sensor / …".
        for child in (tree.get("Children") or []):
            cls._walk(child, [], out)
        return out

    @classmethod
    def _walk(cls, node: dict, path: list, out: dict) -> None:
        text = node.get("Text") or "?"
        new_path = path + [text]
        kids = node.get("Children") or []
        raw_value = node.get("Value")
        # Treat any node whose Value parses as a number as a sensor
        # leaf. Don't return after — wrappers technically CAN carry a
        # Value (LHM sometimes echoes a summary value on a parent) but
        # we still want to walk their children. The full path includes
        # this node's own Text segment because the "Sensor" root is
        # already stripped one level up.
        if raw_value:
            m = cls._NUM_RE.match(str(raw_value).strip())
            if m:
                num_str = m.group(1).replace(",", ".")
                try:
                    val = float(num_str)
                except ValueError:
                    val = None
                unit = m.group(2).strip()
                if val is not None:
                    out[" / ".join(new_path)] = {
                        "value": round(val, 2),
                        "raw":   str(raw_value),
                        "unit":  unit,
                    }
        for kid in kids:
            cls._walk(kid, new_path, out)


class NowPlayingPoller:
    """Watches Windows' SystemMediaTransportControls for the active
    media session and publishes `{title, artist, album, paused,
    position, duration, ts}` so the now-playing widget can render
    whatever's playing. Works with Spotify, Groove, Chrome+YouTube,
    Edge, anything that registers an SMTC session.

    Implementation: a dedicated asyncio loop on a daemon thread polls
    `SMTCManager.request_async() → get_current_session()` every
    second and runs `try_get_media_properties_async()`. The result is
    cached in `_snapshot` and read lock-free by the sysstats poller
    (single-writer / multiple-reader, dict-replace is atomic in
    CPython).

    When the `winrt-Windows.Media.Control` package isn't bundled
    (e.g. dev runs without optional deps), start() prints a notice and
    the snapshot stays empty — sysstats just won't include
    `nowPlaying` and the widget renders its `--` placeholder.
    """

    POLL_INTERVAL_S = 1.0

    def __init__(self, should_poll=None):
        self._stop     = threading.Event()
        self._snapshot: dict = {}
        self._thread: threading.Thread | None = None
        self._available = False
        # v1.2.8: callable()->bool gate. When supplied and returns
        # False we skip the SMTC tick entirely — saves a 1 Hz IPC
        # roundtrip Bridge→NPSMSvc→Spotify (and the DWM/WebView2
        # render cascade that Spotify triggers in response) when no
        # wallpaper page is even connected to consume the snapshot.
        self._should_poll = should_poll
        # v1.2.8: cached SMTCManager singleton. winrt's
        # request_async() advertises returning the same manager each
        # call but the COM ref-counting in winrt-Python isn't always
        # clean on repeated calls, so we resolve it once on the first
        # tick and reuse on every subsequent tick. This is the single
        # biggest source of the NPSMSvc / Spotify / DWM cascade load
        # the user observed when the bridge was under stress.
        self._mgr = None
        try:
            # Detect optional deps once at construction so we don't
            # eat the import cost on every poll if they're missing.
            import winrt.windows.media.control  # noqa: F401
            self._available = True
        except Exception as e:
            print(f"[nowplaying] winrt missing — widget will show n/a ({e})")

    def start(self):
        if not self._available:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="nowplaying-poll")
        self._thread.start()
        print("[nowplaying] poller running (1 Hz, idle-gated)")

    def stop(self):
        self._stop.set()

    def get_snapshot(self) -> dict:
        # CPython dict-attr read is atomic; no lock needed.
        return self._snapshot

    def _run(self):
        # Dedicated asyncio loop so we can await the SMTC API without
        # nesting on the main bridge loop.
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        except Exception as e:
            print(f"[nowplaying] loop init failed: {e}")
            return
        try:
            while not self._stop.is_set():
                # v1.2.8: idle-gate. If no wallpaper page is connected,
                # skip the SMTC roundtrip — nothing on the receiving
                # end can render the snapshot anyway, and the IPC
                # cascade (NPSMSvc → Spotify → DWM) is the load the
                # user observed building up.
                try:
                    poll = self._should_poll() if self._should_poll else True
                except Exception:
                    poll = True
                if poll:
                    try:
                        snap = loop.run_until_complete(self._tick())
                        if snap is not None:
                            self._snapshot = snap
                    except Exception as e:
                        # Keep going even when SMTC throws — common during
                        # session-switch (track change), the next tick recovers.
                        if not isinstance(e, asyncio.CancelledError):
                            print(f"[nowplaying] tick failed: {e}")
                if self._stop.wait(self.POLL_INTERVAL_S):
                    return
        finally:
            try: loop.close()
            except Exception: pass

    async def _tick(self) -> dict | None:
        if self._mgr is None:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as _Mgr,
            )
            self._mgr = await _Mgr.request_async()
        mgr = self._mgr
        session = mgr.get_current_session()
        if session is None:
            return {}   # no media playing
        try:
            props = await session.try_get_media_properties_async()
        except Exception:
            props = None
        playback = session.get_playback_info()
        timeline = session.get_timeline_properties()
        # PlaybackStatus enum: 0=Closed, 1=Opened, 2=Changing, 3=Stopped,
        # 4=Playing, 5=Paused. We only care "playing now?" — anything
        # other than 4 counts as paused for the widget's pause icon.
        playing = int(getattr(playback, "playback_status", 0)) == 4
        # winrt's timespan exposes total_seconds() in newer builds; on
        # older ones it's a python timedelta. Both have .total_seconds.
        def _secs(x) -> float:
            if x is None:
                return 0.0
            try: return float(x.total_seconds())
            except Exception:
                try: return float(x.duration.total_seconds())
                except Exception: return 0.0
        return {
            "title":    (getattr(props, "title", "") or "") if props else "",
            "artist":   (getattr(props, "artist", "") or "") if props else "",
            "album":    (getattr(props, "album_title", "") or "") if props else "",
            "paused":   (not playing),
            "position": _secs(getattr(timeline, "position", None)),
            "duration": _secs(getattr(timeline, "end_time", None)),
            "ts":       int(time.time() * 1000),
        }


class SysStatsPoller:
    """Polls CPU / RAM / network counters via psutil once per second on its
    own daemon thread and pushes a snapshot through Broadcaster.push_sysstats.
    Disables itself (no-op) when psutil isn't available so the rest of the
    bridge still runs.

    Optionally merges in an `hwmon` dict from a sibling HwMonPoller so
    the wallpaper page sees CPU/GPU temps, fan RPMs and voltages in the
    same payload its existing CPU/RAM widgets already drain."""

    def __init__(self, broadcaster: 'Broadcaster',
                 hwmon: 'HwMonPoller | None' = None,
                 nowplaying: 'NowPlayingPoller | None' = None,
                 should_poll=None):
        self.broadcaster = broadcaster
        self.hwmon = hwmon
        self.nowplaying = nowplaying
        # v1.2.10: callable()->bool gate. False = skip the psutil
        # collect + WS push entirely (the snapshot wouldn't have a
        # widget reader, so there's no point even sampling). The
        # default `has_any_clients`-only gate from v1.2.8 still
        # polled whenever a wallpaper page was open; v1.2.10's
        # widget-aware gate is the proper "zero cost when nothing
        # consumes the data" behaviour.
        self._should_poll = should_poll
        self._stop = threading.Event()
        self._last_net = None       # (sent, recv) from previous tick
        self._last_net_ts = 0.0
        self._boot_time = time.time()
        if _HAS_PSUTIL:
            try:
                self._boot_time = psutil.boot_time()
            except Exception:
                pass

    def start(self):
        if not _HAS_PSUTIL:
            print("[sysstats] psutil missing — CPU / RAM / Net widgets will show 'n/a'")
            return
        threading.Thread(target=self._run, daemon=True, name="sysstats-poll").start()
        print("[sysstats] poller running (1 Hz)")

    def stop(self):
        self._stop.set()

    def _run(self):
        # Seed the per-CPU sampler so the first reading isn't a misleading 0
        # (psutil.cpu_percent compares against a previous probe).
        try: psutil.cpu_percent(interval=None)
        except Exception: pass
        while not self._stop.is_set():
            # v1.2.10: widget-aware idle-gate. Skip psutil's full
            # collect + push when no widget consuming sysstats data
            # (cpu-meter, ram-meter, hardware-sensor via hwmon merge,
            # now-playing via nowplaying merge) is placed.
            try:
                poll = self._should_poll() if self._should_poll else \
                       bool(self.broadcaster.has_any_clients())
            except Exception:
                poll = True
            if poll:
                try:
                    snap = self._collect()
                    self.broadcaster.push_sysstats_threadsafe(snap)
                except Exception as e:
                    print(f"[sysstats] tick failed: {e}")
            if self._stop.wait(1.0):
                return

    def _collect(self) -> dict:
        cpu = float(psutil.cpu_percent(interval=None))
        mem = psutil.virtual_memory()
        ram = float(mem.percent)
        # net_io_counters is monotonically increasing; derive a rate by
        # diffing against the previous sample. First call yields 0 since
        # we have no baseline yet.
        now = time.monotonic()
        net = psutil.net_io_counters()
        if self._last_net and self._last_net_ts:
            dt = max(1e-3, now - self._last_net_ts)
            net_down = max(0.0, (net.bytes_recv - self._last_net[0]) / dt)
            net_up   = max(0.0, (net.bytes_sent - self._last_net[1]) / dt)
        else:
            net_down = 0.0
            net_up   = 0.0
        self._last_net    = (net.bytes_recv, net.bytes_sent)
        self._last_net_ts = now
        snap = {
            "cpu":     round(cpu, 1),
            "ram":     round(ram, 1),
            "netDown": round(net_down, 0),
            "netUp":   round(net_up, 0),
            "uptime":  int(time.time() - self._boot_time),
            "ts":      int(time.time() * 1000),
        }
        if self.hwmon is not None:
            # Per-sensor sub-dict: { "AMD Ryzen … / Temperatures / Core …":
            # { value, raw, unit }, … }. Empty when LHM isn't running so
            # widgets can show their `--` placeholder instead of stale data.
            snap["hwmon"] = self.hwmon.get_snapshot()
        if self.nowplaying is not None:
            np_snap = self.nowplaying.get_snapshot()
            if np_snap:
                snap["nowPlaying"] = np_snap
        return snap


class CycleScheduler:
    """Per-screen background poller that flips the active wallpaper to
    the next library entry every `cycle.intervalMin` minutes when
    enabled. Runs as a single thread that wakes every 30 s and walks
    every active screen — cheap because each screen's check is just a
    config read and a wall-clock compare.

    Mirror screens are skipped explicitly: the source's cycle drives
    their bgImage via the existing `_replicate_to_mirrors` path, so
    running the cycle twice would just thrash the mirror with extra
    file writes.
    """

    POLL_INTERVAL_S = 30.0

    def __init__(self, bridge_runtime):
        self.bridge = bridge_runtime
        self._stop  = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="cycle-scheduler")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        # First tick fires after one POLL_INTERVAL so a freshly-started
        # bridge doesn't immediately shuffle on top of whatever the
        # user last set manually.
        while not self._stop.wait(self.POLL_INTERVAL_S):
            try:
                self._tick()
            except Exception as e:
                print(f"[cycle] tick crashed: {e}")

    def _tick(self):
        now_ms = int(time.time() * 1000)
        # v2.3.0-beta hotfix: the BridgeRuntime API is _get_screen_count
        # (underscored). Pre-2.3.0-beta this method was never reached
        # because the cycle scheduler started disabled — the moment the
        # user enabled cycle.enabled on any screen, the next 30 s tick
        # crashed with `AttributeError: 'BridgeRuntime' object has no
        # attribute 'get_screen_count'`. Logs in
        # %LOCALAPPDATA%\SignalRGBWallpaper\logs surfaced the
        # `[cycle] tick crashed` line for users who hit fullscreen
        # pause / resume edges that touched the scheduler path.
        screen_count = int(self.bridge._get_screen_count())
        for i in range(screen_count):
            try:
                with self.bridge.config_lock:
                    s = self.bridge.config.get("screens", {}).get(str(i))
                    if not isinstance(s, dict):
                        continue
                    cycle = s.get("cycle") or {}
                    if not cycle.get("enabled"):
                        continue
                    if s.get("mirrorOf") is not None:
                        continue
                    interval_ms = max(60_000,
                                      int(cycle.get("intervalMin", 10)) * 60_000)
                    last_ms     = int(cycle.get("lastApplyMs") or 0)
                    if last_ms > 0 and (now_ms - last_ms) < interval_ms:
                        continue
                    pool_name = cycle.get("pool", "all")
                    order     = cycle.get("order", "sequential")
                    next_idx  = int(cycle.get("nextIdx") or 0)
                self._cycle_screen(i, pool_name, order, next_idx, now_ms)
            except Exception as e:
                print(f"[cycle] screen={i} failed: {e}")

    def _cycle_screen(self, screen: int, pool_name: str, order: str,
                      next_idx: int, now_ms: int) -> None:
        lib = library_dir()
        cat_path = lib / "library.json"
        if not cat_path.exists():
            return
        try:
            cat = json.loads(cat_path.read_text(encoding="utf-8"))
        except Exception:
            return
        items = cat.get("items", [])
        # v1.6.1-beta library categories: "backgrounds" pool only
        # picks items the user has flagged as Background or Both —
        # Templates (Builder source material) stay out of the
        # auto-cycle rotation. "pinned" filter is unchanged (orthogonal
        # to category). Default "all" still considers every entry so
        # an existing user who has never set a category sees the
        # same behaviour they had before.
        if pool_name == "pinned":
            items = [it for it in items if isinstance(it, dict) and it.get("pinned")]
        elif pool_name == "backgrounds":
            items = [it for it in items if isinstance(it, dict) and "file" in it
                     and (it.get("category") or "both") in ("background", "both")]
        else:
            items = [it for it in items if isinstance(it, dict) and "file" in it]
        if not items:
            return
        if order == "random":
            # Pick any item except the one currently showing if we can
            # tell from the current bgImage path.
            with self.bridge.config_lock:
                s = self.bridge.config["screens"].get(str(screen), {})
                cur_path = str(s.get("bgImage") or "")
            cur_name = os.path.basename(cur_path)
            choices = [it for it in items if it.get("file") != cur_name] or items
            pick = random.choice(choices)
            chosen_idx = items.index(pick)
        else:
            chosen_idx = next_idx % len(items)
            pick = items[chosen_idx]
        file = pick.get("file")
        if not file:
            return
        fp = lib / file
        if not fp.is_file():
            return
        try:
            data = fp.read_bytes()
        except Exception as e:
            print(f"[cycle] read {fp} failed: {e}")
            return
        # _update_background handles bgImage path + replication to
        # mirrors + the new-config-pushed-to-WS dance.
        ok = self.bridge._update_background(screen, data)
        if not ok:
            return
        # Bookkeeping: record when we fired + advance the sequential
        # pointer. These live inside `cycle` so they're persisted.
        with self.bridge.config_lock:
            s = self.bridge.config.get("screens", {}).get(str(screen))
            if isinstance(s, dict):
                cy = s.setdefault("cycle", {})
                cy["lastApplyMs"] = now_ms
                cy["nextIdx"] = (chosen_idx + 1) % len(items)
                cfg_snapshot = json.loads(json.dumps(self.bridge.config))
        try:
            save_config(cfg_snapshot)
        except Exception as e:
            print(f"[cycle] save_config failed: {e}")
        print(f"[cycle] screen={screen} -> {file} (pool={pool_name}, order={order})")


class HotkeyListener:
    """Win32 global hotkey registration + dispatch. Registers
    Ctrl+Shift+1..4 to fire preset-apply on each screen's matching
    slot — one hotkey activates that slot's snapshot on every
    active screen at once, so the whole desktop's look swaps in a
    single keystroke.

    Implementation: each hotkey lives on this listener thread via
    `RegisterHotKey(NULL, id, MOD_CTRL|MOD_SHIFT, vk)`; the thread
    pumps GetMessage to receive WM_HOTKEY. Stop posts WM_QUIT so the
    blocking GetMessage returns and the loop exits.

    Disabled: Stop() unregisters the hotkeys so other apps can grab
    Ctrl+Shift+1..4 again. Re-enable by Start()ing a fresh listener.
    """

    # Modifier flags from WinUser.h.
    _MOD_SHIFT   = 0x0004
    _MOD_CONTROL = 0x0002
    _WM_HOTKEY   = 0x0312
    _WM_QUIT     = 0x0012

    # (hotkey-id, modifiers, virtual-key, preset-slot).
    _HOTKEYS = [
        (1, _MOD_CONTROL | _MOD_SHIFT, 0x31, 0),  # Ctrl+Shift+1 -> slot 0
        (2, _MOD_CONTROL | _MOD_SHIFT, 0x32, 1),  # Ctrl+Shift+2 -> slot 1
        (3, _MOD_CONTROL | _MOD_SHIFT, 0x33, 2),  # Ctrl+Shift+3 -> slot 2
        (4, _MOD_CONTROL | _MOD_SHIFT, 0x34, 3),  # Ctrl+Shift+4 -> slot 3
    ]

    def __init__(self, bridge_runtime):
        self.bridge   = bridge_runtime
        self._thread: threading.Thread | None = None
        self._tid     = 0
        self._enabled = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._enabled = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="hotkey-listener")
        self._thread.start()

    def stop(self):
        self._enabled = False
        if not self._thread or not self._tid:
            return
        try:
            user32 = ctypes.windll.user32
            # Post WM_QUIT to break the blocking GetMessage in _run.
            user32.PostThreadMessageW(self._tid, self._WM_QUIT, 0, 0)
        except Exception as e:
            print(f"[hotkey] stop post failed: {e}")

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self):
        try:
            user32  = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
        except Exception as e:
            print(f"[hotkey] ctypes unavailable: {e}")
            return
        self._tid = kernel32.GetCurrentThreadId()
        registered: list[int] = []
        for hk_id, mods, vk, _slot in self._HOTKEYS:
            try:
                # `hwnd=None` registers the hotkey for the calling
                # thread; messages arrive in this thread's queue.
                if user32.RegisterHotKey(None, hk_id, mods, vk):
                    registered.append(hk_id)
                else:
                    print(f"[hotkey] register id={hk_id} failed "
                          f"(probably already in use by another app)")
            except Exception as e:
                print(f"[hotkey] register id={hk_id} crashed: {e}")
        if not registered:
            print("[hotkey] no hotkeys registered; listener idle")
            return
        print(f"[hotkey] active — Ctrl+Shift+1..{len(registered)} = preset slot 1..{len(registered)}")
        try:
            from ctypes import wintypes
            msg = wintypes.MSG()
            while self._enabled:
                # GetMessageW returns 0 on WM_QUIT, -1 on error, >0 otherwise.
                bret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if bret <= 0:
                    break
                if msg.message == self._WM_HOTKEY:
                    slot = self._slot_for_id(int(msg.wParam))
                    if slot is not None:
                        self._fire_preset(slot)
        finally:
            for hk_id in registered:
                try: user32.UnregisterHotKey(None, hk_id)
                except Exception: pass
            self._tid = 0

    def _slot_for_id(self, hk_id: int) -> int | None:
        for id_, _mods, _vk, slot in self._HOTKEYS:
            if id_ == hk_id:
                return slot
        return None

    def _fire_preset(self, slot: int) -> None:
        """Apply the matching preset slot on every active screen.
        Mirrors are already skipped by `apply_preset` via
        `_block_if_mirror`, so we don't double-fire there."""
        try:
            count = int(self.bridge._get_screen_count())
        except Exception:
            count = 1
        applied = 0
        for i in range(count):
            try:
                if self.bridge.apply_preset(i, slot) is not None:
                    applied += 1
            except Exception as e:
                print(f"[hotkey] apply_preset screen={i} slot={slot} failed: {e}")
        print(f"[hotkey] slot={slot} applied to {applied}/{count} screen(s)")


class ProfileWatcher:
    """Foreground-window watcher that swaps presets based on which exe
    is currently focused. Rule schema:

        {
          "id":         "p_…",   # unique
          "enabled":    True,
          "exe":        "cyberpunk2077.exe",   # case-insensitive
          "screen":     0,                     # 0..N-1 or None (= all)
          "presetSlot": 1,                     # 0..3
          "label":      "Cyberpunk 2077"       # user-friendly, optional
        }

    Stored under `config.profiles` (list). The watcher polls
    `GetForegroundWindow → QueryFullProcessImageName` every second,
    activates the first matching rule, and snapshots the previous
    per-screen state so deactivation restores it. Only one rule is
    active at a time — when the foreground changes to something else
    matched by a different rule, we revert + activate cleanly.

    Mirrored screens are handled implicitly: `apply_preset` rejects on
    mirrors, so the source's preset apply naturally fans out via
    `_replicate_to_mirrors`.
    """

    POLL_INTERVAL_S = 1.0

    def __init__(self, bridge_runtime):
        self.bridge   = bridge_runtime
        self._stop    = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_rule_id: str | None = None
        # screen -> snapshot dict (full screen settings at activation time).
        # On revert we restore PRESET_SNAPSHOT_KEYS only — the same key
        # set save/apply_preset uses, so we don't drift fields the rule
        # didn't touch.
        self._stash: dict[int, dict] = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="profile-watcher")
        self._thread.start()
        print("[profiles] watcher running (1 Hz)")

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self.POLL_INTERVAL_S):
            try:
                self._tick()
            except Exception as e:
                print(f"[profiles] tick failed: {e}")

    def _tick(self):
        with self.bridge.config_lock:
            raw_rules = list(self.bridge.config.get("profiles", []) or [])
        enabled = [r for r in raw_rules
                   if isinstance(r, dict) and r.get("enabled") and r.get("exe")]
        if not enabled:
            if self._active_rule_id is not None:
                self._revert()
            return
        exe = self._foreground_exe()
        matched = None
        for r in enabled:
            target = str(r.get("exe", "")).strip().lower()
            if target and target == exe:
                matched = r
                break
        if matched is None:
            if self._active_rule_id is not None:
                self._revert()
            return
        rule_id = str(matched.get("id") or "")
        if rule_id == self._active_rule_id:
            return   # already active, nothing to do
        # Different rule → swap. Revert previous first so the stash
        # snapshot reflects the user's manual state, not the prior
        # rule's preset.
        if self._active_rule_id is not None:
            self._revert()
        self._activate(matched)

    def _foreground_exe(self) -> str:
        if not _user32:
            return ""
        try:
            kernel32 = ctypes.windll.kernel32
            hwnd = _user32.GetForegroundWindow()
            if not hwnd:
                return ""
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return ""
            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000 — works on
            # processes the bridge can't fully open (e.g. system
            # processes), which is what we want for foreground check.
            h = kernel32.OpenProcess(0x1000, False, pid.value)
            if not h:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(len(buf))
                if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    return ""
                return os.path.basename(buf.value).lower()
            finally:
                kernel32.CloseHandle(h)
        except Exception:
            return ""

    def _screens_for_rule(self, rule: dict) -> list[int]:
        screen = rule.get("screen")
        count  = int(self.bridge._get_screen_count())
        if screen is None or screen == "" or screen == "all":
            return list(range(count))
        try:
            n = int(screen)
        except (TypeError, ValueError):
            return list(range(count))
        if 0 <= n < count:
            return [n]
        return []

    def _activate(self, rule: dict):
        slot = int(rule.get("presetSlot", 0) or 0)
        if not (0 <= slot < PRESET_SLOTS):
            return
        screens = self._screens_for_rule(rule)
        # Snapshot current state for each target screen BEFORE applying
        # so revert restores precisely what the user had.
        for s in screens:
            try:
                with self.bridge.config_lock:
                    cur = self.bridge.config.get("screens", {}).get(str(s)) or {}
                    self._stash[s] = copy.deepcopy(cur)
            except Exception:
                pass
        applied = 0
        for s in screens:
            if self.bridge.apply_preset(s, slot) is not None:
                applied += 1
        self._active_rule_id = str(rule.get("id") or "")
        label = rule.get("label") or rule.get("exe") or "(rule)"
        print(f"[profiles] activated {label!r} -> slot {slot} on {applied}/{len(screens)} screen(s)")

    def _revert(self):
        if not self._stash:
            self._active_rule_id = None
            return
        # Write back the snapshot's PRESET_SNAPSHOT_KEYS values to each
        # stashed screen + push the new settings.
        for s, stash in list(self._stash.items()):
            try:
                def mutate(cur, _snap=stash):
                    for k in PRESET_SNAPSHOT_KEYS:
                        if k in _snap:
                            cur[k] = copy.deepcopy(_snap[k])
                    # v1.6.1-beta R2.2: restore the stashed `cycle`'s
                    # user-config subset only so rotation runtime
                    # state (lastApplyMs / nextIdx) keeps moving
                    # while the profile was active.
                    snap_cycle = _snap.get("cycle")
                    if isinstance(snap_cycle, dict):
                        cur.setdefault("cycle",
                                       dict(DEFAULT_SCREEN_SETTINGS["cycle"]))
                        for k in PRESET_CYCLE_SUBKEYS:
                            if k in snap_cycle:
                                cur["cycle"][k] = snap_cycle[k]
                snap = self.bridge._mutate_screen(s, mutate)
                if snap is not None:
                    self.bridge.push_settings(s, snap)
                    self.bridge._replicate_to_mirrors(s)
            except Exception as e:
                print(f"[profiles] revert screen={s} failed: {e}")
        self._stash.clear()
        prior = self._active_rule_id
        self._active_rule_id = None
        print(f"[profiles] reverted (was {prior!r})")


class UdpReceiver(asyncio.DatagramProtocol):
    """Accepts two wire formats from the SignalRGB plugin:

      • Single-packet  "SR" — original 7-byte header + full RGB payload.
                       Forwarded verbatim. Used when the frame fits in
                       SignalRGB's per-packet UDP cap (≤ 36×36).
      • Chunked        "SC" — 12-byte header carrying frameId/chunkIdx/
                       chunkCount/dims/pixelOffset. Bridge buffers chunks
                       per (screen, frameId) and only forwards once every
                       chunk has arrived. Stale partials (different frameId
                       or older than 200 ms) are evicted lazily as new
                       chunks come in.
    """

    # Partials keyed by (screen, frameId). Each entry tracks dims, expected
    # chunk count, the RGB bytes accumulator, and the per-chunk arrival
    # bitmap so we know when reassembly is complete.
    _STALE_AFTER_S = 0.2

    def __init__(self, broadcaster: Broadcaster,
                 source_mgr: "SourceManager",
                 loop: asyncio.AbstractEventLoop):
        self.broadcaster = broadcaster
        # v1.5.0-beta: every dispatch funnels through SourceManager so
        # the user's per-screen source pick (SignalRGB vs OpenRGB vs
        # sACN) gates whether the frame actually reaches the wallpaper.
        # Pause / has_clients gates stay on the broadcaster — they're
        # cheaper than re-checking config on every datagram and the
        # SourceManager is a no-op for screens still on SignalRGB.
        self.source_mgr = source_mgr
        self.loop = loop
        self.count = 0
        self.warned_bad = 0
        self.partials: dict[tuple[int, int], dict] = {}
        self._chunk_count = 0
        # v1.2.12: rolling per-screen UDP arrival rate. Used to surface
        # the SignalRGB plugin's actual send rate in the Configurator
        # ("Plugin is sending at ~165 fps") so users can pick a frameRate
        # cap that makes sense for their workload. Sampled by counting
        # frames inside a 1 s sliding window per screen — cheap, no
        # background thread.
        self._fps_window_start_per_screen: dict[int, float] = {}
        self._fps_counter_per_screen: dict[int, int] = {}
        self._fps_measured_per_screen: dict[int, float] = {}

    def _bump_fps(self, screen: int) -> None:
        """Account one inbound frame for `screen` and slide the 1 s
        window forward when it expires."""
        now = self.loop.time()
        start = self._fps_window_start_per_screen.get(screen, 0.0)
        if now - start >= 1.0:
            # Window closed — commit the count as the measured rate
            # and reset for the next second.
            self._fps_measured_per_screen[screen] = float(
                self._fps_counter_per_screen.get(screen, 0))
            self._fps_counter_per_screen[screen] = 1
            self._fps_window_start_per_screen[screen] = now
        else:
            self._fps_counter_per_screen[screen] = \
                self._fps_counter_per_screen.get(screen, 0) + 1

    def get_measured_fps(self, screen: int) -> float:
        """Most recent fully-sampled 1 s frame rate for `screen`.
        Returns 0.0 until the first window closes."""
        return self._fps_measured_per_screen.get(screen, 0.0)

    def datagram_received(self, data: bytes, addr):
        if len(data) < 7 or data[0] != 0x53:
            if self.warned_bad < 3:
                self.warned_bad += 1
                print(f"[udp] malformed datagram from {addr}: len={len(data)} head={data[:8].hex()}")
            return
        # v1.2.7: short-circuit before any broadcaster work if the
        # bridge is paused (tray / fullscreen) or no client is
        # listening on this screen. The SignalRGB plugin keeps
        # sending at 60+ Hz × N screens regardless of whether anyone
        # is consuming the data — and prior versions still ran the
        # full encode/task-creation path for each packet, which over
        # ~12 h showed up as ~23 % CPU + a steadily growing Python
        # heap from the per-frame bytes allocations. Doing this gate
        # in datagram_received (sync, on the loop's selector thread)
        # avoids spinning up an asyncio.Task per dropped frame.
        magic1 = data[1]
        screen_hint = data[2] if len(data) >= 3 else 0
        try:
            if self.broadcaster.get_paused():
                return
        except Exception:
            pass
        if not self.broadcaster.has_clients_for(screen_hint):
            return
        if magic1 == 0x52:           # 'R' — original single-packet frame
            screen = data[2]
            self.count += 1
            self._bump_fps(screen)
            # v2.4.3: throttled from every 600 frames — see the matching
            # note on the chunked path below. Same message, same flood.
            if self.count == 1 or self.count % 30000 == 0:
                print(f"[udp] {self.count} single-packet frames "
                      f"(last: screen={screen}, {len(data)} bytes)")
            self.source_mgr.emit(screen, data, "signalrgb")
            return
        if magic1 == 0x43:           # 'C' — chunked frame
            # _bump_fps fires once per assembled frame inside
            # _handle_chunked, not once per chunk — see the success
            # branch there.
            self._handle_chunked(data, addr)
            return
        if self.warned_bad < 3:
            self.warned_bad += 1
            print(f"[udp] unknown magic from {addr}: head={data[:4].hex()}")

    def _handle_chunked(self, data: bytes, addr):
        if len(data) < 12:
            return
        screen      = data[2]
        frame_id    = data[3]
        chunk_idx   = data[4]
        chunk_count = data[5]
        w = (data[6]  << 8) | data[7]
        h = (data[8]  << 8) | data[9]
        pixel_off = (data[10] << 8) | data[11]
        payload   = data[12:]
        expected_payload_bytes = len(payload)
        if chunk_count == 0 or chunk_idx >= chunk_count:
            return
        if w * h <= 0 or w * h > 1 << 18:        # sanity ceiling (~262 K pixels)
            return
        key = (screen, frame_id)
        part = self.partials.get(key)
        # Different (screen, frameId) → fresh entry. We also evict any other
        # partials for this screen whose frame_id differs and that's older
        # than STALE_AFTER_S: out-of-order packets after a frame switch
        # would otherwise pile up.
        now = self.loop.time()
        if part is None:
            # Allocate the assembled RGB buffer up front
            try:
                part = {
                    "w": w, "h": h,
                    "count": chunk_count,
                    "rgb": bytearray(w * h * 3),
                    "got": [False] * chunk_count,
                    "got_count": 0,
                    "started": now,
                }
            except (MemoryError, OverflowError):
                return
            self.partials[key] = part
            self._evict_stale(now, exclude=key)
        # Sanity: dims must match the partial. If a misbehaving sender
        # changes dims mid-frame we drop the whole partial and start over.
        if part["w"] != w or part["h"] != h or part["count"] != chunk_count:
            del self.partials[key]
            return
        # Bounds-check the payload against the partial's RGB buffer.
        rgb_off = pixel_off * 3
        if rgb_off + expected_payload_bytes > len(part["rgb"]):
            del self.partials[key]
            return
        if part["got"][chunk_idx]:
            return                                # duplicate chunk — ignore
        part["rgb"][rgb_off:rgb_off + expected_payload_bytes] = payload
        part["got"][chunk_idx] = True
        part["got_count"] += 1
        self._chunk_count += 1
        if part["got_count"] >= chunk_count:
            # Reassembled — synthesise an SR frame so downstream code stays
            # unchanged. 7-byte header + the RGB blob we just filled.
            frame = bytearray(7 + len(part["rgb"]))
            frame[0] = 0x53; frame[1] = 0x52
            frame[2] = screen
            frame[3] = (w >> 8) & 0xff; frame[4] = w & 0xff
            frame[5] = (h >> 8) & 0xff; frame[6] = h & 0xff
            frame[7:] = part["rgb"]
            del self.partials[key]
            self.count += 1
            self._bump_fps(screen)
            # v2.4.3: this line used to fire every 600 frames — at 30-60 Hz
            # that's every ~10-20 s, and it accounted for ~95 % of the
            # rotating log. A diagnostics bundle from a machine that had
            # been up overnight contained 46 267 copies of it and had
            # rolled almost everything else out of the 4 MiB ringbuffer,
            # including the client counts that eventually identified the
            # bug. Keep the first (proves the chunked path works at all)
            # and then one every 30 000 frames as a liveness marker.
            if self.count == 1 or self.count % 30000 == 0:
                print(f"[udp] {self.count} chunked frames assembled "
                      f"(last: screen={screen}, {w}x{h}, {chunk_count} chunks)")
            self.source_mgr.emit(screen, bytes(frame), "signalrgb")

    def _evict_stale(self, now: float, exclude: tuple[int, int] | None = None):
        for k, p in list(self.partials.items()):
            if k == exclude:
                continue
            if now - p["started"] > self._STALE_AFTER_S:
                del self.partials[k]


# ============================================================================
# Bridge thread — owns the asyncio loop
# ============================================================================

class SourceManager:
    """v1.5.0-beta: routes incoming colour frames from multiple sources
    (SignalRGB UDP plugin, OpenRGB polled device, sACN/E1.31 universe)
    to the broadcaster, gated by per-screen source config.

    Every input — `UdpReceiver` for SignalRGB, `OpenRgbInputManager`
    for OpenRGB polling, `SacnInputManager` for sACN — funnels through
    `emit()` (loop thread) or `emit_threadsafe()` (worker thread).
    The manager looks up the configured source type for that screen
    and drops the frame if it doesn't match, so a still-running
    SignalRGB plugin can't fight an OpenRGB-as-source screen.

    Polled sources (OpenRGB / sACN) build short SR-format frames (a
    4×4 grid of the picked colour) via `flat_color_to_sr_frame()` so
    downstream Broadcaster / frame-tap code doesn't need to care that
    the data didn't originate from a SignalRGB UDP datagram."""

    def __init__(self, bridge_runtime, broadcaster):
        self.bridge = bridge_runtime
        self.broadcaster = broadcaster

    # ── config lookup ──────────────────────────────────────────────────

    def configured_source(self, screen: int) -> str:
        """Returns the source type currently selected for `screen`,
        falling back to "signalrgb" on any config oddity. Cheap +
        lock-free: the config dict is set up by the loader and only
        rewritten as a whole on settings updates, so a stale read
        just costs one wasted dispatch."""
        try:
            sources = self.bridge.config.get("sources") or {}
            src = sources.get(str(screen)) or {}
            t = src.get("type")
            # v1.6.2-beta: "openrgb-sdk" added — the SDK-server-driven
            # source where OpenRGB GUI effects feed into the wallpaper.
            if t in ("signalrgb", "openrgb", "sacn", "openrgb-sdk"):
                return t
        except Exception:
            pass
        return "signalrgb"

    def source_config(self, screen: int) -> dict:
        try:
            sources = self.bridge.config.get("sources") or {}
            src = sources.get(str(screen))
            return dict(src) if isinstance(src, dict) else {}
        except Exception:
            return {}

    # ── emit (called by the various sources) ───────────────────────────

    def emit(self, screen: int, payload: bytes, source: str) -> None:
        """Loop-thread variant. Caller is on the asyncio thread (used
        by UdpReceiver from datagram_received)."""
        if self.configured_source(screen) != source:
            return
        loop = self.broadcaster.loop
        loop.create_task(self.broadcaster.broadcast_frame(screen, payload))

    def emit_threadsafe(self, screen: int, payload: bytes,
                         source: str) -> None:
        """Worker-thread variant. Hops to the asyncio loop via
        `run_coroutine_threadsafe`. Used by OpenRgbInputManager /
        SacnInputManager — both run in their own daemon threads."""
        if self.configured_source(screen) != source:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.broadcaster.broadcast_frame(screen, payload),
                self.broadcaster.loop)
        except Exception as e:
            print(f"[source] emit_threadsafe failed: {e}")

    # ── status (for /sources/status HTTP endpoint) ─────────────────────

    def get_status(self) -> dict:
        """Snapshot of per-screen source types for the Configurator."""
        try:
            sc = max(1, int(self.bridge.config.get("screenCount") or 1))
        except Exception:
            sc = 1
        return {
            "screenCount": sc,
            "sources": {
                str(n): {
                    "type":   self.configured_source(n),
                    "config": self.source_config(n),
                }
                for n in range(N_SCREENS)
            },
        }


def flat_color_to_sr_frame(screen: int,
                            rgb: tuple[int, int, int],
                            grid_size: int = 4) -> bytes:
    """v1.5.0-beta: synthesise a SignalRGB-format wire frame from a
    single colour. Used by the polled / inbound sources so the rest of
    the pipeline (Broadcaster, wallpaper page) doesn't need a separate
    code path. A 4×4 grid is plenty for the wallpaper's blur kernel
    and keeps the WS payload at 55 bytes."""
    w = h = max(1, int(grid_size))
    r = int(rgb[0]) & 0xff
    g = int(rgb[1]) & 0xff
    b = int(rgb[2]) & 0xff
    header = struct.pack(">BBBHH", 0x53, 0x52, screen & 0xff, w, h)
    return header + bytes((r, g, b)) * (w * h)


# ============================================================================
# OpenRGB output manager (v1.4.0-beta)
# ============================================================================

class OpenRgbOutputManager:
    """v1.4.0-beta MVP: a daemon thread that owns the OpenRGB SDK
    connection and pushes the wallpaper's live glow colour stream out
    to OpenRGB-controlled hardware.

    Pipeline:
      Broadcaster.broadcast_frame
        → frame_tap(screen, payload) [sync, on loop thread]
          → updates self._latest_color[screen] with that frame's
            averaged RGB
      worker thread (this class)
        → at ~30 Hz, pushes self._latest_color[<source_screen>] to
          every OpenRGB device via OpenRGBClient.push_color

    The on-loop tap is intentionally cheap (just averages the RGB
    bytes) so it doesn't slow the WS broadcast path; the worker
    thread owns the network I/O.

    Per-screen routing (which screen drives which device) + per-device
    mode (average vs strip vs custom) are roadmap items — this MVP
    just averages the source-screen colour into every connected
    OpenRGB device.

    Reconnect strategy: on any push failure or initial connect
    failure, sleep with exponential backoff (capped at 30 s) before
    retrying. Disabled-state config check runs every second so the
    user can toggle the feature off without restarting the bridge."""

    PUSH_INTERVAL_S = 1.0 / 30.0   # 30 Hz max output rate to OpenRGB

    def __init__(self, bridge_runtime):
        self.bridge = bridge_runtime
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client = None        # OpenRGBClient | None
        # v1.5.0-beta spatial-mapping: store the FULL latest RGB grid
        # per screen (w, h, raw_bytes) instead of just an averaged
        # colour. The worker thread samples per device at its
        # configured (x, y) — see _sample_color. CPython dict
        # assignment is atomic so no lock is needed between the
        # frame-tap (loop thread) and the worker (daemon thread).
        # Total memory bounded by N_SCREENS × max_grid × 3, which
        # for SignalRGB's typical 32×32 grid is ~12 KiB.
        self._latest_grid: dict[int, tuple] = {}
        # Status surfaced to /openrgb/status (configurator polls it).
        self._connected = False
        self._last_error: str = ""
        self._last_connect_ts: float = 0.0
        self._device_summary: list = []

    # ── public API ─────────────────────────────────────────────────────

    def start(self) -> None:
        if _OpenRGBClient is None:
            print("[openrgb] client module unavailable — output disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="openrgb-output")
        self._thread.start()
        print("[openrgb] output manager started (will connect on demand)")

    def stop(self) -> None:
        self._stop.set()

    def on_frame(self, screen: int, payload: bytes) -> None:
        """Frame-tap entry point. Called sync on the asyncio loop
        thread for every UDP frame that passes Broadcaster's rate cap.
        v1.5.0-beta spatial-mapping: stores the FULL grid so the
        worker can sample per device at its configured (x, y). The
        Configurator's preview canvas also reads this via the WS
        broadcast — same source-of-truth, no second tap needed."""
        if not self._is_enabled():
            return
        # SignalRGB wire format: [S][R][screen][wH][wL][hH][hL][rgb…]
        if len(payload) < 7:
            return
        w = (payload[3] << 8) | payload[4]
        h = (payload[5] << 8) | payload[6]
        total = w * h
        if total <= 0:
            return
        data = payload[7:7 + total * 3]
        if len(data) < total * 3:
            return
        # Tuple-assignment is atomic in CPython — worker thread either
        # sees the old (w, h, data) triple or the new one, never a
        # partial mix.
        self._latest_grid[screen] = (w, h, bytes(data))

    def _sample_color(self, screen: int,
                      x_norm: float, y_norm: float) -> tuple:
        """Nearest-neighbour sample at the given normalised position
        on `screen`'s latest grid. Returns black when no frame has
        arrived yet (matches the "page is loading" colour the
        wallpaper itself shows)."""
        grid = self._latest_grid.get(screen)
        if grid is None:
            return (0, 0, 0)
        w, h, data = grid
        sx = max(0, min(w - 1, int(x_norm * w)))
        sy = max(0, min(h - 1, int(y_norm * h)))
        off = (sy * w + sx) * 3
        return (data[off], data[off + 1], data[off + 2])

    def _sample_strip(self, screen: int,
                      x1: float, y1: float,
                      x2: float, y2: float,
                      led_count: int) -> list:
        """v1.5.0-beta strip mode: sample `led_count` evenly spaced
        points along the (x1,y1)→(x2,y2) line on `screen`'s latest
        grid. Returns a list of (r,g,b) triples ready for
        `OpenRGBClient.push_strip`. Lets a multi-LED device (RAM,
        light strip, keyboard row) show a gradient that follows
        the wallpaper underneath instead of one averaged colour.

        Endpoints inclusive: LED 0 sits at (x1,y1), LED N-1 at
        (x2,y2). Single-LED devices collapse to the start point —
        equivalent to point mode anchored at (x1,y1)."""
        grid = self._latest_grid.get(screen)
        if grid is None or led_count <= 0:
            return [(0, 0, 0)] * max(0, led_count)
        w, h, data = grid
        out: list = []
        denom = max(1, led_count - 1)
        for i in range(led_count):
            t = i / denom
            xt = x1 + (x2 - x1) * t
            yt = y1 + (y2 - y1) * t
            sx = max(0, min(w - 1, int(xt * w)))
            sy = max(0, min(h - 1, int(yt * h)))
            off = (sy * w + sx) * 3
            out.append((data[off], data[off + 1], data[off + 2]))
        return out

    def get_status(self) -> dict:
        """Snapshot for the Configurator's status polling. Includes
        the connect state, last error, and enumerated device list.

        v1.5.0-beta-hotfix2: also includes the bridge's APP_VERSION
        so the Configurator can detect a stale installer (an Inno
        run that didn't replace a locked exe leaves the running
        process on the previous build), plus the OpenRGB client's
        per-device parseErrors so a misaligned struct surfaces in
        the UI instead of just an empty `devices` list."""
        client = self._client
        # v1.5.0-beta spatial-mapping: re-merge the live deviceMapping
        # into each device entry so a drag in the Configurator shows
        # up on the next poll without waiting for the next connect.
        live_map = self._cfg().get("deviceMapping") or {}
        devices_out = []
        for d in self._device_summary:
            entry = dict(d)
            m = live_map.get(str(entry.get("id")))
            entry["mapping"] = (
                m if isinstance(m, dict) else entry.get("mapping")
                or {"x": 0.5, "y": 0.5}
            )
            devices_out.append(entry)
        return {
            "available":     _OpenRGBClient is not None,
            "enabled":       self._is_enabled(),
            "connected":     self._connected,
            "lastError":     self._last_error,
            "lastConnectTs": self._last_connect_ts,
            "devices":       devices_out,
            "sourceScreen":  self._source_screen(),
            "bridgeVersion": APP_VERSION,
            "protocolUsed":  getattr(client, "protocol_version", 0)
                              if client else 0,
            "parseErrors":   list(getattr(client, "last_parse_errors", []) or [])
                              if client else [],
        }

    # ── config helpers ─────────────────────────────────────────────────

    def _cfg(self) -> dict:
        try:
            with self.bridge.config_lock:
                return dict(self.bridge.config.get("openrgbOutput") or {})
        except Exception:
            return {}

    def _is_enabled(self) -> bool:
        return bool(self._cfg().get("enabled", False))

    def _source_screen(self) -> int:
        try:
            return max(0, int(self._cfg().get("sourceScreen", 0)))
        except Exception:
            return 0

    # ── worker loop ────────────────────────────────────────────────────

    def _run(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            if not self._is_enabled():
                # Disabled — close any open connection, idle-wait.
                if self._client and self._client.connected:
                    try: self._client.disconnect()
                    except Exception: pass
                self._connected = False
                if self._stop.wait(1.0):
                    return
                backoff = 2.0
                continue
            cfg = self._cfg()
            host = str(cfg.get("host") or "127.0.0.1")
            port = int(cfg.get("port") or 6742)
            # (Re)connect if needed.
            if self._client is None or not self._client.connected:
                self._client = _OpenRGBClient(host, port)
                if not self._client.connect():
                    self._connected = False
                    self._last_error = "connect failed"
                    self._device_summary = []
                    if self._stop.wait(backoff):
                        return
                    backoff = min(30.0, backoff * 1.5)
                    continue
                self._connected = True
                self._last_error = ""
                self._last_connect_ts = time.time()
                # v1.5.0-beta spatial-mapping: surface each device's
                # current (x, y) position so the Configurator can
                # render markers at the right spot on first paint
                # without an extra round trip.
                _map_now = self._cfg().get("deviceMapping") or {}
                self._device_summary = [
                    {
                        "id": d["id"],
                        "name": d["name"],
                        "ledCount": d["led_count"],
                        "mapping": (
                            _map_now.get(str(d["id"]))
                            if isinstance(_map_now.get(str(d["id"])), dict)
                            else {"x": 0.5, "y": 0.5}
                        ),
                    }
                    for d in self._client.devices
                ]
                backoff = 2.0
                print(f"[openrgb] connected to {host}:{port}, "
                      f"{len(self._client.devices)} device(s)")
            # Push current state to every device. v1.5.0-beta
            # spatial-mapping: each device samples the source-screen's
            # grid at its configured (x, y); a device without an
            # entry in deviceMapping falls back to (0.5, 0.5) which
            # gives the same one-colour-for-everything behaviour as
            # v1.4. Push order is enumerate order; failures cascade
            # the same way as before.
            src_screen = self._source_screen()
            mapping = self._cfg().get("deviceMapping") or {}
            socket_err: str = ""
            for d in self._client.devices:
                led_count = int(d.get("led_count") or 0)
                if led_count <= 0:
                    continue
                pos = mapping.get(str(d["id"]))
                if not isinstance(pos, dict):
                    pos = {"x": 0.5, "y": 0.5}
                try:
                    x_n = float(pos.get("x", 0.5))
                    y_n = float(pos.get("y", 0.5))
                except (TypeError, ValueError):
                    x_n = y_n = 0.5
                # v1.5.0-beta strip mode: when the mapping declares a
                # line (mode=="line" + x2/y2), sample N=led_count
                # points along (x,y)→(x2,y2) and push as a strip so
                # multi-LED devices show a gradient instead of one
                # averaged colour. Otherwise the v1.4-compatible
                # point path runs.
                try:
                    is_line = (pos.get("mode") == "line"
                               and "x2" in pos and "y2" in pos)
                    if is_line:
                        x2_n = float(pos.get("x2", x_n))
                        y2_n = float(pos.get("y2", y_n))
                        colors = self._sample_strip(
                            src_screen, x_n, y_n, x2_n, y2_n, led_count)
                        self._client.push_strip(d["id"], colors)
                    else:
                        color = self._sample_color(src_screen, x_n, y_n)
                        self._client.push_color(d["id"], color)
                except (OSError, _OpenRGBError) as e:
                    socket_err = f"{d.get('name', d['id'])}: {e}"
                    break
                except Exception as e:
                    # Anything else is a programmer bug — log + tear
                    # down the connection so we re-enumerate from
                    # scratch on the next loop pass.
                    socket_err = f"unexpected: {e}"
                    break
            if socket_err:
                self._last_error = f"push failed ({socket_err})"
                try: self._client.disconnect()
                except Exception: pass
                self._connected = False
                if self._stop.wait(1.0):
                    return
                continue
            if self._stop.wait(self.PUSH_INTERVAL_S):
                return


# ============================================================================
# OpenRGB input manager — drives the wallpaper from an OpenRGB device
# ============================================================================

def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """Cheap HSV→RGB conversion for the OpenRGB-SDK effect engine.
    Output is int 0..255 per channel. Pulled into a module-level
    helper so the per-frame loop doesn't pay a method-lookup cost."""
    if s <= 0:
        c = int(v * 255)
        return (c, c, c)
    h6 = (h - int(h)) * 6.0
    sector = int(h6)
    f = h6 - sector
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    if   sector == 0: r, g, b = v, t, p
    elif sector == 1: r, g, b = q, v, p
    elif sector == 2: r, g, b = p, v, t
    elif sector == 3: r, g, b = p, q, v
    elif sector == 4: r, g, b = t, p, v
    else:             r, g, b = v, p, q
    return (int(r * 255), int(g * 255), int(b * 255))


def _rgb_to_hue(rgb: tuple[int, int, int]) -> float:
    """Tiny RGB→hue used by Color Wave so the wave varies around the
    user's picked colour. Saturation/value ignored — only the hue
    angle matters here. Returns 0..1."""
    r, g, b = rgb
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx == mn:
        return 0.0
    d = mx - mn
    if mx == r:
        h = ((g - b) / d) % 6.0
    elif mx == g:
        h = ((b - r) / d) + 2.0
    else:
        h = ((r - g) / d) + 4.0
    return (h / 6.0) % 1.0


class OpenRgbSdkServerManager:
    """v1.6.2-beta: expose the bridge to the OpenRGB GUI / SDK clients
    as a set of virtual matrix devices (one per screen). Reverse
    direction of the v1.4 OpenRGB output / v1.5 OpenRGB input —
    instead of pulling colours from real devices, we let real
    OpenRGB clients PUSH effects ONTO our virtual devices, and
    map those LED writes onto the wallpaper grid.

    Per-screen virtual device:
        name        "Wallpaper Screen N"
        led_count   = matrix[0] * matrix[1]  (W × H)
        matrix_map  row-major LED indices in W × H cells

    Receiving an UpdateLEDs from any connected SDK client
    forwards the colour array to `_on_update_leds`, which Phase 2
    of the v1.6.2-beta cycle wires into the broadcaster so the
    wallpaper page renders SDK-driven colours alongside the
    existing SignalRGB / OpenRGB-input / sACN sources.

    The server lives in `openrgb_server.py`; this class owns its
    lifecycle, config plumbing, and status surface."""

    def __init__(self, bridge_runtime):
        self.bridge = bridge_runtime
        self._server = None
        self._last_error: str = ""
        # Stashed by _on_update_leds — Phase 2 reads these to forward
        # into the broadcaster. Keyed by screen index. Each entry:
        # (last_colors, ts).
        self._last_frames: dict[int, tuple[list, float]] = {}
        self._frames_lock = threading.Lock()
        # v1.6.2-beta hotfix4: built-in effect engine. Runs at 30 Hz
        # while the server is up, renders each device's active mode
        # (when not Direct), and pushes the result through the same
        # _on_update_leds callback Direct uses. Engine reads device
        # state (mode_index / speed / brightness / color) live so
        # GUI mode picks take effect on the next tick.
        # v1.6.5-beta: each generation gets its OWN Event so a fast
        # reload() can't reach into the new generation and clear the
        # old thread's stop flag. The old Event stays set forever
        # → the old thread exits on its next tick + can never be
        # re-armed by start().
        self._engine_stop: threading.Event | None = None
        self._engine_thread: threading.Thread | None = None

    # ── config helpers ─────────────────────────────────────────────

    def _cfg(self) -> dict:
        with self.bridge.config_lock:
            cfg = self.bridge.config.get("openrgbSdkServer") or {}
            return copy.deepcopy(cfg) if isinstance(cfg, dict) else {}

    def _build_devices(self) -> list:
        """Construct one VirtualDevice per ACTIVE screen from config.matrix.

        Active screen count comes from `config.screenCount` (the
        Configurator's screen-count picker). We deliberately do NOT
        expose all N_SCREENS slots — that surfaced ghost devices in
        the OpenRGB GUI for screens the user hadn't enabled, and
        cluttered the device list for typical 1-screen setups."""
        if _OpenRgbVirtualDevice is None:
            return []
        cfg = self._cfg()
        matrix_cfg = cfg.get("matrix") or {}
        with self.bridge.config_lock:
            sc = int(self.bridge.config.get("screenCount") or 1)
        sc = max(1, min(N_SCREENS, sc))
        devices = []
        for n in range(sc):
            m = matrix_cfg.get(str(n)) or [32, 16]
            if (not isinstance(m, (list, tuple)) or len(m) != 2
                    or not all(isinstance(v, int) and v > 0 for v in m)):
                m = [32, 16]
            w, h = int(m[0]), int(m[1])
            devices.append(_OpenRgbVirtualDevice(
                screen_idx=n,
                name=f"Wallpaper Screen {n + 1}",
                width=w, height=h,
            ))
        return devices

    # ── lifecycle ──────────────────────────────────────────────────

    def start(self) -> None:
        """Start the SDK server if the module loaded AND config has
        `enabled: true`. Returns silently otherwise so existing
        installs that haven't opted in pay zero."""
        if _OpenRgbSdkServer is None:
            print("[openrgb-sdk] server module unavailable — feature off")
            return
        cfg = self._cfg()
        if not cfg.get("enabled"):
            print("[openrgb-sdk] disabled in config — not starting")
            return
        host = str(cfg.get("host") or "0.0.0.0")
        port = int(cfg.get("port") or 6743)
        devices = self._build_devices()
        self._server = _OpenRgbSdkServer(
            devices=devices,
            on_update_leds=self._on_update_leds,
            host=host, port=port,
        )
        if not self._server.start():
            self._last_error = self._server.last_error
            self._server = None
            return
        # Effect engine — renders non-Direct modes at 30 Hz into the
        # same UpdateLEDs callback path Direct uses. v1.6.5-beta:
        # spawn a NEW Event for this generation. The old generation
        # (if any) holds onto its own Event in its closure via
        # _effect_loop's stop_evt argument — start() never reaches
        # in to clear it, so a join-timeout from stop() can't
        # resurrect the old thread.
        stop_evt = threading.Event()
        self._engine_stop = stop_evt
        self._engine_thread = threading.Thread(
            target=self._effect_loop, args=(stop_evt,),
            daemon=True, name="openrgb-sdk-effects")
        self._engine_thread.start()

    def stop(self) -> None:
        if self._engine_stop is not None:
            self._engine_stop.set()
        # v1.6.4-beta: join the engine thread so a fast reload()
        # can't briefly run the old + new engine in parallel. The
        # loop polls its OWN stop event (passed as argument) so a
        # subsequent start() that allocates a fresh Event leaves
        # the old one signalled forever — the old thread exits
        # cleanly even if join() times out.
        prev = self._engine_thread
        if prev is not None and prev.is_alive():
            try: prev.join(timeout=0.2)
            except Exception: pass
        if self._server is not None:
            try: self._server.stop()
            except Exception as e:
                print(f"[openrgb-sdk] stop failed: {e}")
            self._server = None
        self._engine_thread = None
        with self._frames_lock:
            self._last_frames.clear()

    def reload(self) -> None:
        """Tear down + start anew. Called when config.enabled / port /
        matrix changes via the Configurator's setting-update channel."""
        self.stop()
        self.start()

    # ── effect engine ──────────────────────────────────────────────

    def _effect_loop(self, stop_evt: threading.Event) -> None:
        """30-Hz render loop. For each connected device whose active
        mode is NOT Direct, computes the colour array for the current
        frame from the device's mode + speed + brightness + colour,
        then forwards it through _on_update_leds — same path Direct
        uses, so the wallpaper / SourceManager routing stays uniform.

        Direct is skipped because the GUI will be sending its own
        UpdateLEDs writes; running the engine on top would cause
        last-write-wins flicker.

        `stop_evt` is the per-generation stop signal — passed in by
        start() so a subsequent reload()'s start() that allocates a
        fresh Event can't reach in and clear OUR stop flag."""
        TICK_S = 1.0 / 30.0
        t0 = time.monotonic()
        while not stop_evt.is_set():
            if self._server is None:
                if stop_evt.wait(TICK_S):
                    return
                continue
            devices = list(self._server._devices)
            now = time.monotonic() - t0
            for dev in devices:
                if dev.mode_index <= 0:
                    continue   # Direct — engine no-op
                try:
                    colors = self._render_mode(dev, now)
                except Exception as e:
                    print(f"[openrgb-sdk] render {dev.name} failed: {e}")
                    continue
                if colors:
                    try:
                        self._on_update_leds(dev.screen_idx, colors)
                    except Exception as e:
                        print(f"[openrgb-sdk] engine emit failed: {e}")
            if stop_evt.wait(TICK_S):
                return

    def _render_mode(self, dev, now: float) -> list:
        """Compute one frame's worth of (R, G, B) tuples for `dev`.
        Speed slider 0..100 maps to per-mode cadence; brightness
        0..100 scales output linearly."""
        n = dev.led_count
        if n <= 0:
            return []
        # Brightness as 0..1.
        b = max(0.0, min(1.0, dev.brightness / 100.0))
        # Mode index 1..len(BUILTIN_MODES)-1.
        # See openrgb_server.BUILTIN_MODES for the index → name table.
        idx = dev.mode_index
        # Static: solid colour.
        if idx == 1:
            r, g, gb = (int(c * b) for c in dev.color)
            return [(r, g, gb)] * n
        # Speed scaling — map 0..100 to ~0.05..2 Hz.
        spd = max(0.05, dev.speed / 50.0)
        if idx == 2:
            # Breathing — sin(2πft) over device.color.
            amp = 0.5 + 0.5 * math.sin(2 * math.pi * spd * 0.5 * now)
            scale = amp * b
            r, g, bl = (int(c * scale) for c in dev.color)
            return [(r, g, bl)] * n
        if idx == 3:
            # Rainbow — uniform hue cycle across all LEDs.
            h = (now * spd * 0.2) % 1.0
            r, g, bl = _hsv_to_rgb(h, 1.0, b)
            return [(r, g, bl)] * n
        # v1.6.4-beta: direction-aware wave rendering for Rainbow Wave +
        # Color Wave. OpenRGB direction enum:
        #   0 = LEFT, 1 = RIGHT, 2 = UP, 3 = DOWN,
        #   4 = HORIZONTAL, 5 = VERTICAL
        # Vertical (UP/DOWN) iterates rows; HV-axis enums are aliases
        # to one direction each.
        #
        # v1.6.5-beta: OpenRGB convention has LEFT increment hue_base
        # and RIGHT decrement — visually the pattern moves leftward
        # for LEFT, rightward for RIGHT. Our previous wiring inverted
        # this. Swapped: LEFT (d=0) / UP (d=2) now reverse the time
        # sign (-t), RIGHT (d=1) / DOWN (d=3) keep +t. HORIZONTAL
        # (4) / VERTICAL (5) stay as the forward defaults.
        d = dev.direction
        if idx == 4 or idx == 5:
            w, h = dev.width, dev.height
            vertical = (d == 2 or d == 3 or d == 5)
            reverse  = (d == 0 or d == 2)
            extent = h if vertical else w
            line_colors = []
            if idx == 4:
                for i in range(extent):
                    pos = (i / max(1, extent - 1))
                    t = now * spd * 0.2
                    hue = ((pos + (-t if reverse else t))) % 1.0
                    line_colors.append(_hsv_to_rgb(hue, 1.0, b))
            else:
                # v1.6.5-beta: when the user-picked colour is
                # grayscale (default white before any explicit pick),
                # _rgb_to_hue returns 0 → Color Wave centres on red.
                # That's a surprising default. Fall back to a calm
                # cyan-blue (0.55) so the wave reads as "colour
                # wave" rather than "red wave" until the user picks
                # something deliberate.
                base_h = _rgb_to_hue(dev.color)
                if base_h == 0.0 and dev.color[0] == dev.color[1] == dev.color[2]:
                    base_h = 0.55
                for i in range(extent):
                    pos = (i / max(1, extent - 1))
                    t = now * spd * 0.2
                    offset = math.sin(2 * math.pi
                                       * (pos + (-t if reverse else t)))
                    hue = (base_h + 0.15 * offset) % 1.0
                    line_colors.append(_hsv_to_rgb(hue, 1.0, b))
            # Build the W*H output. Vertical: each row r gets
            # line_colors[r] across all W columns. Horizontal: each row
            # gets the full line_colors array repeated.
            out = []
            if vertical:
                for row in range(h):
                    col = line_colors[row]
                    out.extend([col] * w)
            else:
                for _ in range(h):
                    out.extend(line_colors)
            return out
        return []

    # ── UpdateLEDs callback ────────────────────────────────────────

    def _on_update_leds(self, screen_idx: int,
                        colors: list[tuple[int, int, int]]) -> None:
        """Fired by `openrgb_server.OpenRgbSdkServer` for every
        RGBCONTROLLER_UPDATELEDS / UPDATEZONELEDS it receives. Stashes
        the latest array per screen for the status endpoint, then —
        when the screen's configured source is `openrgb-sdk` — encodes
        the colours into the SignalRGB wire format and pushes through
        SourceManager so the wallpaper page renders them like any
        other source frame.

        SourceManager drops emits when the configured source for that
        screen doesn't match; that's the same per-screen gating the
        OpenRGB-input + sACN-input feeds already rely on. If the user
        flips the source picker away from openrgb-sdk on a given
        screen, the existing SignalRGB / OpenRGB-input / sACN feed
        takes over without any explicit re-routing here."""
        if not (0 <= screen_idx < N_SCREENS):
            return
        with self._frames_lock:
            self._last_frames[screen_idx] = (colors, time.time())
        # Build the SignalRGB-format frame from the virtual device's
        # matrix dimensions (W × H). Wire format:
        #   [S][R][screen u8][wH u8][wL u8][hH u8][hL u8][rgb...]
        # We need the width/height we ADVERTISED to OpenRGB so the
        # wallpaper page's zone layout matches the colour array.
        cfg = self._cfg()
        matrix_cfg = cfg.get("matrix") or {}
        dims = matrix_cfg.get(str(screen_idx)) or [32, 16]
        try:
            w = int(dims[0]); h = int(dims[1])
        except (TypeError, ValueError, IndexError):
            w, h = 32, 16
        expected_len = w * h
        # Pad or truncate the incoming colours to exactly W*H. Effects
        # that target a different LED count would otherwise misalign
        # the row stride and produce a slanted picture.
        if len(colors) < expected_len:
            colors = list(colors) + [(0, 0, 0)] * (expected_len - len(colors))
        elif len(colors) > expected_len:
            colors = list(colors)[:expected_len]
        header = bytes((0x53, 0x52, screen_idx & 0xff,
                        (w >> 8) & 0xff, w & 0xff,
                        (h >> 8) & 0xff, h & 0xff))
        body = bytearray(3 * expected_len)
        di = 0
        for r, g, b in colors:
            body[di]     = r & 0xff
            body[di + 1] = g & 0xff
            body[di + 2] = b & 0xff
            di += 3
        payload = header + bytes(body)
        # Route via SourceManager — its `configured_source` check drops
        # the emit silently when the user has the screen pointed at a
        # different source type. No extra plumbing needed for that.
        try:
            self.bridge.source_mgr.emit_threadsafe(
                screen_idx, payload, "openrgb-sdk")
        except Exception as e:
            print(f"[openrgb-sdk] emit failed for screen {screen_idx}: {e}")

    # ── status (Configurator polls every ~2s) ──────────────────────

    def get_status(self) -> dict:
        if self._server is None:
            return {
                "available": _OpenRgbSdkServer is not None,
                "running":   False,
                "lastError": self._last_error,
                "devices":   [],
            }
        s = self._server.status()
        # Decorate with per-screen update timestamps + colour-sample
        # so the UI can show "last frame received 0.2s ago" per device.
        with self._frames_lock:
            samples = {}
            for n, (cols, ts) in self._last_frames.items():
                # First colour as RGB triple, plus ts (epoch s).
                first = list(cols[0]) if cols else None
                samples[str(n)] = {"firstColor": first,
                                    "lastUpdateMs": int(ts * 1000)}
        s["perScreen"] = samples
        s["available"] = True
        return s


class OpenRgbInputManager:
    """v1.5.0-beta: poll OpenRGB devices and feed their current LED
    colours into the wallpaper as a colour source. Mirror image of
    `OpenRgbOutputManager` — same client class, but `get_colors()`
    instead of `push_color()`.

    Per-screen device selection lives in `config.sources[screen]`:
        {type: "openrgb", host, port, deviceIndex}

    Multiple screens can target the same (host, port) — we de-dup
    the connection. Connection failures fall back to the standard
    exponential-backoff retry; the worker idles whenever no screens
    are using the OpenRGB source type."""

    POLL_INTERVAL_S = 1.0 / 30.0

    def __init__(self, bridge_runtime, source_mgr):
        self.bridge = bridge_runtime
        self.source_mgr = source_mgr
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # (host, port) -> OpenRGBClient. One TCP connection per
        # unique endpoint, regardless of how many screens point at it.
        self._clients: dict[tuple[str, int], object] = {}
        self._last_error: str = ""

    def start(self) -> None:
        if _OpenRGBClient is None:
            print("[openrgb-in] client module unavailable — input disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="openrgb-input")
        self._thread.start()
        print("[openrgb-in] input manager started")

    def stop(self) -> None:
        self._stop.set()

    def get_status(self) -> dict:
        return {
            "available":  _OpenRGBClient is not None,
            "endpoints":  [
                {"host": h, "port": p,
                 "connected": bool(getattr(c, "connected", False))}
                for (h, p), c in self._clients.items()
            ],
            "lastError":  self._last_error,
        }

    # ── worker loop ────────────────────────────────────────────────────

    def _openrgb_screens(self) -> list[tuple[int, dict]]:
        """Returns [(screen_idx, src_cfg), …] for screens that the
        user has switched onto the OpenRGB source. Snapshot read; the
        SourceManager handles the actual per-frame gate."""
        out: list[tuple[int, dict]] = []
        try:
            sources = self.bridge.config.get("sources") or {}
            sc = max(1, int(self.bridge.config.get("screenCount") or 1))
            for n in range(sc):
                src = sources.get(str(n)) or {}
                if isinstance(src, dict) and src.get("type") == "openrgb":
                    out.append((n, dict(src)))
        except Exception:
            pass
        return out

    def _client_for(self, host: str, port: int):
        """Get-or-create a connected client for the given endpoint.
        Returns None on connect failure (worker keeps idling)."""
        key = (host, port)
        client = self._clients.get(key)
        if client is not None and client.connected:
            return client
        client = _OpenRGBClient(host, port)
        if not client.connect():
            self._last_error = f"connect failed: {host}:{port}"
            return None
        self._clients[key] = client
        self._last_error = ""
        print(f"[openrgb-in] connected to {host}:{port}, "
              f"{len(client.devices)} device(s)")
        return client

    def _run(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            screens = self._openrgb_screens()
            if not screens:
                # No OpenRGB-sourced screens — drop any open connections
                # so the user doesn't see lingering sockets to OpenRGB
                # after switching the screens back to SignalRGB.
                if self._clients:
                    for c in self._clients.values():
                        try: c.disconnect()
                        except Exception: pass
                    self._clients.clear()
                if self._stop.wait(1.0):
                    return
                backoff = 2.0
                continue
            any_failure = False
            for screen, cfg in screens:
                host = str(cfg.get("host") or "127.0.0.1")
                port = int(cfg.get("port") or 6742)
                device_index = max(0, int(cfg.get("deviceIndex") or 0))
                client = self._client_for(host, port)
                if client is None:
                    any_failure = True
                    continue
                # v1.5.0-beta hotfix7: split socket-broken from
                # empty-colours. get_colors() now re-raises OSError /
                # OpenRGBError on real wire problems so we trigger
                # reconnect; a returned empty list is a legitimate
                # "device reports no colours" (hardware-effect mode,
                # mid-mode-switch, …) — keep polling at full rate
                # without burning backoff cycles.
                try:
                    colors = client.get_colors(device_index)
                except (OSError, _OpenRGBError) as e:
                    self._last_error = f"{host}:{port} dev{device_index}: {e}"
                    any_failure = True
                    continue
                if not colors:
                    # Push black so the wallpaper visibly reflects the
                    # "OpenRGB device is in a mode we can't read" state
                    # instead of freezing on the last-known colour. No
                    # backoff escalation — the connection is healthy.
                    frame = flat_color_to_sr_frame(screen, (0, 0, 0))
                    self.source_mgr.emit_threadsafe(screen, frame, "openrgb")
                    continue
                # Average all LEDs of the device so per-LED variations
                # don't dominate the wallpaper glow. The user picked the
                # device, not the specific LED — averaging is the
                # least-surprising default. (A future enhancement could
                # add a "specific LED" mode in source_config.)
                n = len(colors)
                r_sum = sum(c[0] for c in colors)
                g_sum = sum(c[1] for c in colors)
                b_sum = sum(c[2] for c in colors)
                avg = (r_sum // n, g_sum // n, b_sum // n)
                frame = flat_color_to_sr_frame(screen, avg)
                self.source_mgr.emit_threadsafe(screen, frame, "openrgb")
            if any_failure:
                # Close clients that lost their connections so the next
                # tick can rebuild.
                for key, c in list(self._clients.items()):
                    if not getattr(c, "connected", False):
                        del self._clients[key]
                if self._stop.wait(backoff):
                    return
                backoff = min(30.0, backoff * 1.5)
                continue
            backoff = 2.0
            if self._stop.wait(self.POLL_INTERVAL_S):
                return


# ============================================================================
# sACN/E1.31 input manager — drives the wallpaper from a multicast universe
# ============================================================================

class SacnInputManager:
    """v1.5.0-beta: listen on the E1.31 multicast group(s) for every
    screen the user has switched onto the sACN source, and feed the
    first three DMX channels of each universe (R, G, B) into the
    wallpaper. Joins one multicast group per unique universe; bind
    once on UDP port 5568 with SO_REUSEADDR so other sACN tools on
    the same host (testers, monitors) keep working alongside us."""

    # E1.31 senders re-announce universes every ~10 s. Catalogue
    # entries that haven't been refreshed for 3× that window are
    # considered stale (sender went offline) and dropped.
    _DISCOVERY_STALE_S = 35.0

    def __init__(self, bridge_runtime, source_mgr):
        self.bridge = bridge_runtime
        self.source_mgr = source_mgr
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock = None
        self._joined_groups: set[int] = set()
        self._last_seq_by_universe: dict[int, int] = {}
        self._last_error: str = ""
        self._last_rx_ts: float = 0.0
        self._rx_count: int = 0
        # v1.5.0-beta sACN discovery: passively listen on
        # 239.255.250.214 for E1.31 Universe Discovery packets.
        # Catalogue keyed by hex(CID) so a single sender announcing
        # multiple universes shows up as one entry. Surfaced via
        # /api/v1/sacn/discovered + /sacn-discovery for the
        # Configurator's universe pick-list.
        self._discovered: dict[str, dict] = {}
        self._discovery_joined = False

    def start(self) -> None:
        if _sacn is None:
            print("[sacn-in] codec unavailable — input disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="sacn-input")
        self._thread.start()
        print("[sacn-in] input manager started")

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try: self._sock.close()
            except Exception: pass

    def get_status(self) -> dict:
        return {
            "available":   _sacn is not None,
            "lastError":   self._last_error,
            "lastRxTs":    self._last_rx_ts,
            "rxCount":     self._rx_count,
            "joined":      sorted(self._joined_groups),
            "discovered":  self.get_discovered(),
        }

    def get_discovered(self) -> list:
        """v1.5.0-beta sACN discovery: list of {cid, sourceName,
        universes, lastSeen} for every sender currently announcing
        on the network. Stale entries (>35 s without a re-announce)
        are pruned on read."""
        now = time.time()
        out: list = []
        for cid_hex, entry in list(self._discovered.items()):
            if now - entry.get("lastSeen", 0) > self._DISCOVERY_STALE_S:
                del self._discovered[cid_hex]
                continue
            out.append({
                "cid":        cid_hex,
                "sourceName": entry.get("sourceName") or "",
                "universes":  sorted(entry.get("universes") or []),
                "lastSeen":   entry.get("lastSeen"),
            })
        # Deterministic ordering by source name for stable UI render.
        out.sort(key=lambda e: (e["sourceName"], e["cid"]))
        return out

    def _wanted_universes(self) -> dict[int, int]:
        """{universe -> screen} for every sACN-typed screen. If two
        screens point at the same universe the later wins (Configurator
        prevents this in normal use)."""
        out: dict[int, int] = {}
        try:
            sources = self.bridge.config.get("sources") or {}
            sc = max(1, int(self.bridge.config.get("screenCount") or 1))
            for n in range(sc):
                src = sources.get(str(n)) or {}
                if isinstance(src, dict) and src.get("type") == "sacn":
                    try:
                        u = int(src.get("universe") or 0)
                    except (TypeError, ValueError):
                        u = 0
                    if 1 <= u <= 63999:
                        out[u] = n
        except Exception:
            pass
        return out

    def _ensure_socket(self) -> bool:
        if self._sock is not None:
            return True
        try:
            import socket as _sock
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
            s.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
            # SO_REUSEPORT isn't available on Windows < some recent
            # build; SO_REUSEADDR is enough for the multicast-share
            # case we care about.
            s.bind(("", _sacn.E131_PORT))
            s.settimeout(0.5)
            self._sock = s
            # Membership state belongs to the old socket — reset so
            # `_ensure_discovery_membership` + `_sync_memberships`
            # re-join cleanly on the new one.
            self._discovery_joined = False
            self._joined_groups.clear()
            return True
        except OSError as e:
            self._last_error = f"bind failed: {e}"
            return False

    def _ensure_discovery_membership(self) -> None:
        """Join the fixed E1.31 Universe Discovery multicast group
        (239.255.250.214) once per socket lifetime. Senders announce
        their universe lists there at ~10 s intervals; we passively
        record what we see and surface it to the Configurator's
        universe pick-list."""
        if self._discovery_joined or self._sock is None:
            return
        try:
            _sacn.join_multicast_group(
                self._sock, _sacn.DISCOVERY_MULTICAST_GROUP)
            self._discovery_joined = True
            print(f"[sacn-in] joined discovery group "
                  f"({_sacn.DISCOVERY_MULTICAST_GROUP})")
        except (OSError, ValueError) as e:
            self._last_error = f"discovery join: {e}"

    def _ingest_discovery(self, data: bytes) -> bool:
        """Try parsing `data` as a Universe Discovery packet. Returns
        True on a successful parse (caller skips the data-packet
        path), False on anything else."""
        info = _sacn.parse_e131_universe_discovery(data)
        if info is None:
            return False
        cid_hex = info["cid"].hex()
        entry = self._discovered.get(cid_hex)
        if entry is None:
            entry = {"sourceName": info["sourceName"],
                     "universes": set(), "lastSeen": time.time()}
            self._discovered[cid_hex] = entry
        # Universe-discovery packets can be paginated when the sender
        # has more universes than fit in one packet; the universe
        # union across pages from one CID gives the full list. We
        # don't track per-page state — instead we just keep adding +
        # the stale-entry sweep drops senders that go silent.
        entry["sourceName"] = info["sourceName"]
        entry["universes"].update(info["universes"])
        entry["lastSeen"] = time.time()
        return True

    def _sync_memberships(self, wanted: dict[int, int]) -> None:
        if self._sock is None:
            return
        want_groups = set(wanted.keys())
        # Join new groups.
        for u in want_groups - self._joined_groups:
            try:
                group = _sacn.multicast_group_for(u)
                _sacn.join_multicast_group(self._sock, group)
                self._joined_groups.add(u)
                print(f"[sacn-in] joined universe {u} ({group})")
            except (OSError, ValueError) as e:
                self._last_error = f"join {u}: {e}"
        # Drop groups we no longer want.
        for u in self._joined_groups - want_groups:
            try:
                import socket as _sock
                group = _sacn.multicast_group_for(u)
                mreq = _sock.inet_aton(group) + _sock.inet_aton("0.0.0.0")
                self._sock.setsockopt(_sock.IPPROTO_IP,
                                       _sock.IP_DROP_MEMBERSHIP, mreq)
                print(f"[sacn-in] left universe {u}")
            except (OSError, ValueError):
                pass
        self._joined_groups &= want_groups

    def _run(self) -> None:
        last_sync = 0.0
        while not self._stop.is_set():
            wanted = self._wanted_universes()
            # v1.5.0-beta sACN discovery: also bind the socket when no
            # sACN source is wired so the discovery group can still be
            # populated (the Configurator pre-shows discovered senders
            # before the user picks one). Discovery-only mode joins
            # ONLY the discovery group; data groups stay closed.
            if not wanted:
                # Discovery mode: ensure socket + discovery membership,
                # idle on recv.
                if not self._ensure_socket():
                    if self._stop.wait(2.0):
                        return
                    continue
                self._ensure_discovery_membership()
                if self._joined_groups:
                    # Drop any data-group memberships left over.
                    self._sync_memberships({})
                try:
                    data, _addr = self._sock.recvfrom(1500)
                except (TimeoutError, OSError):
                    continue
                self._ingest_discovery(data)
                continue
            if not self._ensure_socket():
                if self._stop.wait(2.0):
                    return
                continue
            self._ensure_discovery_membership()
            # Re-sync memberships ~every second; cheap.
            now = time.monotonic()
            if now - last_sync > 1.0:
                self._sync_memberships(wanted)
                last_sync = now
            try:
                data, _addr = self._sock.recvfrom(1500)
            except (TimeoutError, OSError):
                continue
            # Try discovery parse first — cheap, returns None on
            # any non-discovery packet, so the data-packet path runs
            # next without overhead.
            if self._ingest_discovery(data):
                continue
            pkt = _sacn.parse_e131(data)
            if pkt is None:
                continue
            u = pkt["universe"]
            screen = wanted.get(u)
            if screen is None:
                continue
            # Sequence-number jitter: drop packets that arrive
            # older than the last seen one. E1.31 senders are
            # SHOULD-compliant about monotonic sequences but
            # networks reorder; the wallpaper page would jitter
            # if we accepted stale frames.
            prev = self._last_seq_by_universe.get(u, -1)
            seq = pkt["sequence"]
            if prev != -1 and ((seq - prev) % 256) > 128:
                # treat as out-of-order, drop
                continue
            self._last_seq_by_universe[u] = seq
            dmx = pkt["dmx"]
            if len(dmx) < 3:
                continue
            rgb = (dmx[0], dmx[1], dmx[2])
            frame = flat_color_to_sr_frame(screen, rgb)
            self.source_mgr.emit_threadsafe(screen, frame, "sacn")
            self._rx_count += 1
            self._last_rx_ts = time.time()


# ============================================================================
# sACN/E1.31 output emitter — parallel to OpenRgbOutputManager
# ============================================================================

class SacnOutputManager:
    """v1.5.0-beta: emit E1.31 DATA packets carrying the per-screen
    averaged glow colour to one universe per screen. Registered as a
    broadcaster frame-tap (same hook as OpenRgbOutputManager) so we
    pick up exactly the same colour stream the wallpaper page sees.

    The actual UDP TX runs on its own worker thread at 30 Hz so a
    chatty multicast destination can never stall the asyncio loop."""

    PUSH_INTERVAL_S = 1.0 / 30.0

    def __init__(self, bridge_runtime):
        self.bridge = bridge_runtime
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock = None
        # screen → averaged (r, g, b) updated by on_frame
        self._latest_color: dict[int, tuple] = {}
        # universe → sequence counter (rolls mod 256)
        self._seq: dict[int, int] = {}
        self._last_error: str = ""
        self._tx_count: int = 0

    def start(self) -> None:
        if _sacn is None:
            print("[sacn-out] codec unavailable — output disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="sacn-output")
        self._thread.start()
        print("[sacn-out] output manager started (will emit on demand)")

    def stop(self) -> None:
        self._stop.set()

    def get_status(self) -> dict:
        return {
            "available":  _sacn is not None,
            "enabled":    self._is_enabled(),
            "lastError":  self._last_error,
            "txCount":    self._tx_count,
            "universes":  dict(self._cfg().get("universes") or {}),
        }

    def on_frame(self, screen: int, payload: bytes) -> None:
        """Frame-tap. Same averaging as OpenRgbOutputManager.on_frame —
        we deliberately don't share state because a future enhancement
        could let each output have its own source-screen selection."""
        if not self._is_enabled():
            return
        if len(payload) < 7:
            return
        w = (payload[3] << 8) | payload[4]
        h = (payload[5] << 8) | payload[6]
        total = w * h
        if total <= 0:
            return
        data = payload[7:]
        if len(data) < total * 3:
            return
        r_sum = g_sum = b_sum = 0
        off = 0
        for _ in range(total):
            r_sum += data[off]
            g_sum += data[off + 1]
            b_sum += data[off + 2]
            off += 3
        self._latest_color[screen] = (
            r_sum // total, g_sum // total, b_sum // total)

    # ── config helpers ─────────────────────────────────────────────────

    def _cfg(self) -> dict:
        try:
            with self.bridge.config_lock:
                return dict(self.bridge.config.get("sacnOutput") or {})
        except Exception:
            return {}

    def _is_enabled(self) -> bool:
        return bool(self._cfg().get("enabled", False))

    # ── worker loop ────────────────────────────────────────────────────

    def _ensure_socket(self) -> bool:
        if self._sock is not None:
            return True
        try:
            self._sock = _sacn.make_multicast_sender_socket()
            return True
        except OSError as e:
            self._last_error = f"socket: {e}"
            return False

    def _run(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            if not self._is_enabled():
                if self._sock is not None:
                    try: self._sock.close()
                    except Exception: pass
                    self._sock = None
                if self._stop.wait(1.0):
                    return
                backoff = 2.0
                continue
            if not self._ensure_socket():
                if self._stop.wait(backoff):
                    return
                backoff = min(30.0, backoff * 1.5)
                continue
            backoff = 2.0
            cfg = self._cfg()
            destination = str(cfg.get("destination") or "multicast")
            unicast_host = str(cfg.get("unicastHost") or "")
            try:
                priority = max(0, min(200, int(cfg.get("priority") or 100)))
            except (TypeError, ValueError):
                priority = 100
            universes = cfg.get("universes") or {}
            try:
                screen_count = max(1, int(self.bridge.config.get("screenCount") or 1))
            except Exception:
                screen_count = 1
            tx_failed = False
            for n in range(screen_count):
                try:
                    universe = int(universes.get(str(n)) or 0)
                except (TypeError, ValueError):
                    universe = 0
                if not 1 <= universe <= 63999:
                    continue
                color = self._latest_color.get(n, (0, 0, 0))
                # First three DMX slots = R, G, B. Pad to 6 slots so
                # receivers that expect at least one full RGB triplet
                # plus zeros (some hardware quirks) stay happy.
                dmx = bytes((color[0], color[1], color[2], 0, 0, 0))
                seq = self._seq.get(universe, 0)
                try:
                    pkt = _sacn.pack_e131(
                        universe, dmx, sequence=seq, priority=priority)
                except (ValueError, OSError) as e:
                    self._last_error = f"pack {universe}: {e}"
                    continue
                try:
                    if destination == "unicast" and unicast_host:
                        target = (unicast_host, _sacn.E131_PORT)
                    else:
                        target = (
                            _sacn.multicast_group_for(universe),
                            _sacn.E131_PORT)
                    self._sock.sendto(pkt, target)
                    self._tx_count += 1
                except (OSError, ValueError) as e:
                    self._last_error = f"send {universe}: {e}"
                    tx_failed = True
                self._seq[universe] = (seq + 1) & 0xff
            if tx_failed:
                try: self._sock.close()
                except Exception: pass
                self._sock = None
                if self._stop.wait(1.0):
                    return
                continue
            if self._stop.wait(self.PUSH_INTERVAL_S):
                return


# ============================================================================
# MQTT bridge — publish wallpaper state, subscribe to control topics (v1.5)
# ============================================================================

class MqttBridge:
    """v1.5.0-beta: MQTT bridge for Home Assistant + scripts.

    Publishes per-screen state (active preset, manual-pause flag,
    glow colour, current background) under a configurable topic
    prefix, and subscribes to `*/set` topics for control. Designed
    around HA's MQTT-Discovery conventions so adding the bridge as
    an integration is a one-line broker config.

    Topic layout (with the default `signalrgb-wallpaper` prefix):

        signalrgb-wallpaper/bridge/online        retained "online"/"offline"
        signalrgb-wallpaper/bridge/version       retained, app version
        signalrgb-wallpaper/screen/<n>/preset    retained, active slot (or "-")
        signalrgb-wallpaper/screen/<n>/preset/set            apply preset slot
        signalrgb-wallpaper/screen/<n>/pause     retained, "on"/"off"
        signalrgb-wallpaper/screen/<n>/pause/set             "on" / "off"
        signalrgb-wallpaper/screen/<n>/background retained, current bg path
        signalrgb-wallpaper/screen/<n>/glow      retained, "#rrggbb"

    State publishes throttle to once per change — we listen on the
    broadcaster's frame tap for glow updates + push on settings
    push for everything else. The publisher worker thread does the
    keep-alive + reconnect-with-backoff dance."""

    PUBLISH_INTERVAL_S = 1.0      # max state-refresh rate
    RECONNECT_MIN_S    = 2.0
    RECONNECT_MAX_S    = 60.0

    def __init__(self, bridge_runtime):
        self.bridge = bridge_runtime
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client = None
        self._last_error: str = ""
        self._last_connect_ts: float = 0.0
        # Per-screen latest colour cache, populated by the frame tap.
        self._latest_color: dict[int, tuple] = {}
        # Per-screen last-published cache so we only re-publish on change.
        self._published: dict[str, str] = {}
        # Status counters surfaced to /api/v1/mqtt/status.
        self._publish_count = 0
        self._recv_count = 0

    def start(self) -> None:
        if _MQTTClient is None:
            print("[mqtt] client module unavailable — bridge disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="mqtt-bridge")
        self._thread.start()
        print("[mqtt] bridge manager started (will connect on demand)")

    def stop(self) -> None:
        self._stop.set()

    def on_frame(self, screen: int, payload: bytes) -> None:
        """Frame-tap entry point. Averages once + caches; the worker
        publishes the colour on its tick if it changed. Quietly
        skipped when disabled."""
        if not self._is_enabled():
            return
        if len(payload) < 7:
            return
        w = (payload[3] << 8) | payload[4]
        h = (payload[5] << 8) | payload[6]
        total = w * h
        if total <= 0:
            return
        data = payload[7:]
        if len(data) < total * 3:
            return
        r_sum = g_sum = b_sum = 0
        off = 0
        for _ in range(total):
            r_sum += data[off]
            g_sum += data[off + 1]
            b_sum += data[off + 2]
            off += 3
        self._latest_color[screen] = (
            r_sum // total, g_sum // total, b_sum // total)

    def get_status(self) -> dict:
        return {
            "available":     _MQTTClient is not None,
            "enabled":       self._is_enabled(),
            "connected":     bool(self._client and self._client.is_connected),
            "lastError":     self._last_error,
            "lastConnectTs": self._last_connect_ts,
            "publishCount":  self._publish_count,
            "recvCount":     self._recv_count,
            "topicPrefix":   self._cfg().get("topicPrefix", ""),
            "host":          self._cfg().get("host", ""),
        }

    # ── config helpers ─────────────────────────────────────────────────

    def _cfg(self) -> dict:
        try:
            with self.bridge.config_lock:
                return dict(self.bridge.config.get("mqttBridge") or {})
        except Exception:
            return {}

    def _is_enabled(self) -> bool:
        return bool(self._cfg().get("enabled", False))

    def _prefix(self) -> str:
        return str(self._cfg().get("topicPrefix") or "signalrgb-wallpaper")

    # ── publish helpers ────────────────────────────────────────────────

    def _publish_retained(self, suffix: str, payload: str) -> None:
        if not (self._client and self._client.is_connected):
            return
        topic = self._prefix() + "/" + suffix
        if self._published.get(topic) == payload:
            return
        if self._client.publish(topic, payload, retain=True):
            self._published[topic] = payload
            self._publish_count += 1

    def _publish_state_snapshot(self) -> None:
        """One pass of per-screen state publishes. Pulls from the
        bridge's config + the latest frame-tap colour cache."""
        try:
            with self.bridge.config_lock:
                screens_cfg = dict(self.bridge.config.get("screens") or {})
                screen_count = int(self.bridge.config.get("screenCount") or 1)
        except Exception:
            return
        for n in range(screen_count):
            s = screens_cfg.get(str(n)) or {}
            bg = str(s.get("bgImage") or "")
            self._publish_retained(f"screen/{n}/background", bg)
            # Active preset slot — we track this by comparing the
            # current full settings hash to each preset hash. Cheap
            # for the typical 4-slot case.
            active = "-"
            for slot_idx, preset in enumerate(s.get("presets") or []):
                if preset is None:
                    continue
                # Comparing the saved preset shape against `s` is a
                # superset check: we treat the slot as active when
                # bgImage matches (proxy for "this preset is on").
                if preset.get("bgImage") == bg and bg:
                    active = str(slot_idx)
                    break
            self._publish_retained(f"screen/{n}/preset", active)
            colour = self._latest_color.get(n)
            if colour is not None:
                hex_ = f"#{colour[0]:02x}{colour[1]:02x}{colour[2]:02x}"
                self._publish_retained(f"screen/{n}/glow", hex_)
        # Pause state is bridge-global today (manual + fullscreen).
        try:
            paused = self.bridge.is_manual_paused()
        except Exception:
            paused = False
        for n in range(screen_count):
            self._publish_retained(f"screen/{n}/pause",
                                    "on" if paused else "off")

    # ── subscribe callbacks ────────────────────────────────────────────

    def _on_preset_set(self, topic: str, payload: bytes) -> None:
        self._recv_count += 1
        # Topic: <prefix>/screen/<n>/preset/set
        parts = topic.split("/")
        try:
            n = int(parts[parts.index("screen") + 1])
            slot = int(payload.decode("utf-8", "replace").strip())
        except (ValueError, IndexError):
            return
        try:
            self.bridge.apply_preset(n, slot)
        except Exception as e:
            print(f"[mqtt] apply_preset failed: {e}")

    def _on_pause_set(self, topic: str, payload: bytes) -> None:
        self._recv_count += 1
        body = payload.decode("utf-8", "replace").strip().lower()
        paused = body in ("on", "true", "1", "pause", "paused")
        try:
            self.bridge.set_manual_pause(paused)
        except Exception as e:
            print(f"[mqtt] set_manual_pause failed: {e}")

    # ── worker loop ────────────────────────────────────────────────────

    def _disconnect_client(self) -> None:
        if self._client is not None:
            try: self._client.disconnect()
            except Exception: pass
            self._client = None
        self._published.clear()

    def _connect(self) -> bool:
        cfg = self._cfg()
        host       = str(cfg.get("host") or "localhost")
        port       = int(cfg.get("port") or 1883)
        username   = str(cfg.get("username") or "")
        password   = str(cfg.get("password") or "")
        client_id  = str(cfg.get("clientId") or "signalrgb-wallpaper")
        prefix     = str(cfg.get("topicPrefix") or "signalrgb-wallpaper")
        will_topic = prefix + "/bridge/online"
        c = _MQTTClient(host=host, port=port, client_id=client_id,
                         username=username, password=password,
                         will_topic=will_topic,
                         will_payload=b"offline",
                         will_retain=True)
        if not c.connect():
            self._last_error = c.last_error or "connect failed"
            return False
        # Online + version announcements (retained).
        c.publish(will_topic, "online", retain=True)
        c.publish(prefix + "/bridge/version", APP_VERSION, retain=True)
        # Subscribe to control surface.
        c.subscribe(prefix + "/screen/+/preset/set", self._on_preset_set)
        c.subscribe(prefix + "/screen/+/pause/set", self._on_pause_set)
        self._client = c
        self._last_error = ""
        self._last_connect_ts = time.time()
        print(f"[mqtt] connected to {host}:{port} as {client_id}")
        # v1.5.0-beta HA Discovery: publish entity-config payloads so
        # Home Assistant auto-creates one device with N×4 entities
        # (preset select, pause switch, glow + background sensors).
        # Re-published on every reconnect — retained, so HA picks
        # them up even if it boots after the bridge.
        try:
            self._publish_discovery(c, cfg, prefix, client_id)
        except Exception as e:
            print(f"[mqtt] discovery publish failed: {e}")
        return True

    def _publish_discovery(self, client, cfg: dict,
                            prefix: str, client_id: str) -> None:
        """Publish HA MQTT-Discovery config payloads. Blank
        discoveryPrefix suppresses (some users prefer manual YAML
        configuration of sensors)."""
        discovery_prefix = str(cfg.get("discoveryPrefix") or "")
        if not discovery_prefix:
            print("[mqtt] discoveryPrefix blank — skipping HA discovery")
            return
        try:
            with self.bridge.config_lock:
                screen_count = int(self.bridge.config.get("screenCount") or 1)
        except Exception:
            screen_count = 1
        # One device card in HA groups every screen's entities.
        # `identifiers` is what makes HA recognise repeat configs as
        # the same device on reconnect.
        device = {
            "identifiers":  [client_id],
            "name":         "SignalRGB Wallpaper Bridge",
            "manufacturer": "Delido",
            "model":        "Bridge",
            "sw_version":   APP_VERSION,
        }
        availability = {
            "availability_topic":    prefix + "/bridge/online",
            "payload_available":     "online",
            "payload_not_available": "offline",
        }
        # Per-screen entities. HA reads everything under one device.
        for n in range(screen_count):
            base_uid = f"{client_id}_screen{n}"
            # Preset select — slot 0..N-1 + "-" placeholder for "no preset".
            preset_cfg = {
                "name":          f"Screen {n + 1} Preset",
                "unique_id":     f"{base_uid}_preset",
                "object_id":     f"{base_uid}_preset",
                "state_topic":   f"{prefix}/screen/{n}/preset",
                "command_topic": f"{prefix}/screen/{n}/preset/set",
                "options":       ["-"] + [str(i) for i in range(PRESET_SLOTS)],
                "icon":          "mdi:format-list-numbered",
                "device":        device,
                **availability,
            }
            client.publish(
                f"{discovery_prefix}/select/{client_id}/screen{n}_preset/config",
                json.dumps(preset_cfg), retain=True)
            # Pause switch.
            pause_cfg = {
                "name":          f"Screen {n + 1} Pause",
                "unique_id":     f"{base_uid}_pause",
                "object_id":     f"{base_uid}_pause",
                "state_topic":   f"{prefix}/screen/{n}/pause",
                "command_topic": f"{prefix}/screen/{n}/pause/set",
                "payload_on":    "on",
                "payload_off":   "off",
                "icon":          "mdi:pause",
                "device":        device,
                **availability,
            }
            client.publish(
                f"{discovery_prefix}/switch/{client_id}/screen{n}_pause/config",
                json.dumps(pause_cfg), retain=True)
            # Glow colour sensor (#rrggbb hex string).
            glow_cfg = {
                "name":        f"Screen {n + 1} Glow",
                "unique_id":   f"{base_uid}_glow",
                "object_id":   f"{base_uid}_glow",
                "state_topic": f"{prefix}/screen/{n}/glow",
                "icon":        "mdi:palette",
                "device":      device,
                **availability,
            }
            client.publish(
                f"{discovery_prefix}/sensor/{client_id}/screen{n}_glow/config",
                json.dumps(glow_cfg), retain=True)
            # Background path sensor.
            bg_cfg = {
                "name":        f"Screen {n + 1} Background",
                "unique_id":   f"{base_uid}_bg",
                "object_id":   f"{base_uid}_bg",
                "state_topic": f"{prefix}/screen/{n}/background",
                "icon":        "mdi:image",
                "device":      device,
                **availability,
            }
            client.publish(
                f"{discovery_prefix}/sensor/{client_id}/screen{n}_background/config",
                json.dumps(bg_cfg), retain=True)
        print(f"[mqtt] published HA discovery for {screen_count} screen(s) "
              f"under {discovery_prefix}/.../{client_id}/")

    def _run(self) -> None:
        backoff = self.RECONNECT_MIN_S
        while not self._stop.is_set():
            if not self._is_enabled():
                self._disconnect_client()
                if self._stop.wait(1.0):
                    return
                backoff = self.RECONNECT_MIN_S
                continue
            if not (self._client and self._client.is_connected):
                self._disconnect_client()
                if not self._connect():
                    if self._stop.wait(backoff):
                        return
                    backoff = min(self.RECONNECT_MAX_S, backoff * 1.5)
                    continue
                backoff = self.RECONNECT_MIN_S
            try:
                self._publish_state_snapshot()
            except Exception as e:
                self._last_error = f"publish loop: {e}"
            if self._stop.wait(self.PUBLISH_INTERVAL_S):
                return


# ============================================================================
# Plugin registry — third-party widget loader (v1.5.0-beta)
# ============================================================================

class PluginRegistry:
    """v1.5.0-beta: scans `%LOCALAPPDATA%\\SignalRGBWallpaper\\plugins\\`
    on startup and on demand, exposes the discovered plugins to the
    Configurator (catalogue), the wallpaper page (renderer +
    iframe sandbox), and the HTTP file-server (sandboxed serve of
    plugin assets under `/plugins/<name>/<path>`).

    Plugin layout:
        plugins/<name>/manifest.json   required
        plugins/<name>/widget.html     loaded into a sandboxed iframe
        plugins/<name>/icon.svg        optional, picker icon
        plugins/<name>/*               any other assets (css, js, png)

    Manifest schema (all string lengths clamped for safety):
        name            (string)  Stable identifier, used in URL paths
        version         (string)
        label           (string)  Human-readable, shown in the picker
        author          (string)
        description     (string)
        widgetHtml      (string)  Default: "widget.html"
        iconSvg         (string)  Inline SVG markup OR filename
        defaultSize     {w, h}
        defaultOptions  (object)  Initial options for new instances

    Security: the iframe gets `sandbox="allow-scripts"` (no
    same-origin / no top-nav / no forms) and a `Content-Security-
    Policy: default-src 'self'` header on every served file. Plugins
    can't read the main page's DOM, cookies, or the WS — they
    receive everything via postMessage from the wallpaper page."""

    def __init__(self):
        self._plugins: dict[str, dict] = {}
        self._last_scan_ts: float = 0.0
        self._last_error: str = ""
        self.rescan()

    @property
    def root(self) -> Path:
        return config_path().parent / "plugins"

    def rescan(self) -> None:
        d = self.root
        if not d.exists():
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            self._plugins = {}
            self._last_scan_ts = time.time()
            return
        out: dict[str, dict] = {}
        for sub in d.iterdir():
            if not sub.is_dir() or sub.name.startswith("."):
                continue
            manifest_path = sub / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                m = json.loads(manifest_path.read_text("utf-8"))
            except Exception as e:
                self._last_error = f"{sub.name}: {e}"
                print(f"[plugin] {sub.name} manifest load failed: {e}")
                continue
            # Stable identifier — strict alnum/_/- only, prevents
            # path-traversal via the manifest's `name`.
            name = re.sub(r'[^a-zA-Z0-9_-]', '',
                          str(m.get("name") or sub.name))
            if not name:
                continue
            entry = {
                "name":           name,
                "version":        str(m.get("version") or "0.0.0")[:32],
                "label":          str(m.get("label") or name)[:64],
                "author":         str(m.get("author") or "")[:64],
                "description":    str(m.get("description") or "")[:512],
                "widgetHtml":     str(m.get("widgetHtml") or "widget.html")[:128],
                "iconSvg":        str(m.get("iconSvg") or "")[:8192],
                "defaultSize":    m.get("defaultSize") or {"w": 320, "h": 200},
                "defaultOptions": m.get("defaultOptions") or {},
                "folder":         str(sub.resolve()),
            }
            # Sanity-check widgetHtml exists; we don't want a plugin
            # in the catalogue that can't be loaded.
            target = sub / entry["widgetHtml"]
            if not target.exists():
                self._last_error = f"{name}: widgetHtml not found"
                print(f"[plugin] {name}: {entry['widgetHtml']} missing")
                continue
            out[name] = entry
        self._plugins = out
        self._last_scan_ts = time.time()
        print(f"[plugin] scanned {len(out)} plugin(s) under {d}")

    def list_plugins(self) -> list:
        return list(self._plugins.values())

    def get(self, name: str) -> dict | None:
        return self._plugins.get(name)

    def get_status(self) -> dict:
        return {
            "available": True,
            "count":     len(self._plugins),
            "root":      str(self.root),
            "lastScan":  self._last_scan_ts,
            "lastError": self._last_error,
            "plugins":   self.list_plugins(),
        }

    def resolve_asset(self, name: str, rel: str) -> Path | None:
        """Resolve `<folder>/<rel>` for plugin `name`, refusing any
        path that escapes the plugin folder. Used by the HTTP
        `/plugins/<name>/<rel>` handler."""
        plug = self._plugins.get(name)
        if not plug:
            return None
        base = Path(plug["folder"])
        try:
            target = (base / rel).resolve()
            target.relative_to(base)
        except (ValueError, OSError):
            return None
        if not target.is_file():
            return None
        return target


class BridgeRuntime:
    """Lives in a daemon thread, owns the asyncio loop and the broadcaster."""

    def __init__(self, config: dict, config_lock: threading.Lock):
        self.config = config
        self.config_lock = config_lock
        self.loop: asyncio.AbstractEventLoop | None = None
        self.broadcaster: Broadcaster | None = None
        self._ready = threading.Event()
        # _paused is the fullscreen-watcher-driven flag; _manual_paused
        # is the tray's explicit Pause toggle. Effective pause (frame
        # drop + the wallpaper-page PAUSED badge) is the OR of both —
        # see _is_paused(). v1.2.3.
        self._paused = False
        self._manual_paused = False
        self.fullscreen_watcher = FullscreenWatcher(
            on_state_change=self._on_fullscreen_state,
            is_enabled=self._is_fullscreen_pause_enabled,
        )
        # v1.2.1: tray-app reference, set by main() after both the
        # bridge runtime and the tray app exist. Used by the
        # Configurator's `system-action` WS commands to invoke the
        # same handlers the tray's Advanced submenu used to call.
        # None-safe — every callsite null-checks before dispatching.
        self.tray = None

    def placed_widget_types(self) -> set:
        """Set of widget-type strings currently placed across all
        screens. Used by the poller idle-gate so a poller only ticks
        when a widget that consumes its data is actually placed
        somewhere. CPython dict-iteration on `self.config` is atomic
        for snapshot purposes — we deliberately skip `config_lock`
        here because the callable fires every second from background
        threads and a stale read just costs one wasted (or skipped)
        poll which the next second corrects."""
        out = set()
        try:
            for s in (self.config.get("screens", {}) or {}).values():
                if not isinstance(s, dict):
                    continue
                for w in (s.get("widgets", []) or []):
                    if isinstance(w, dict):
                        t = w.get("type")
                        if isinstance(t, str):
                            out.add(t)
        except Exception:
            pass
        return out

    def _poller_gate(self, *widget_types: str):
        """Returns a callable that returns True iff at least one
        wallpaper page is connected AND at least one of the given
        widget types is placed on some screen. Used to drive the
        NowPlaying / HwMon / SysStats pollers — they each run at
        1 Hz, so the closure has to be cheap. Closes over self for
        a fresh snapshot on every call. Fails open on exception so
        a bug here can never silently disable a feature."""
        needed = set(widget_types)
        def gate() -> bool:
            try:
                if not self.broadcaster.has_any_clients():
                    return False
                return bool(needed & self.placed_widget_types())
            except Exception:
                return True
        return gate

    def _get_settings(self, screen: int) -> dict:
        with self.config_lock:
            return dict(self.config["screens"].get(str(screen), DEFAULT_SCREEN_SETTINGS))

    def _get_screen_count(self) -> int:
        with self.config_lock:
            return int(self.config.get("screenCount", 1))

    def _is_paused(self) -> bool:
        # Effective pause = fullscreen-induced OR manual tray toggle.
        return self._paused or self._manual_paused

    def set_manual_pause(self, paused: bool):
        """Tray Pause/Resume entry. Independent of the fullscreen
        watcher — a manual pause holds even when no fullscreen app is
        foreground, and a manual resume doesn't override an active
        fullscreen pause (the watcher's flag stays set until the app
        leaves foreground)."""
        self._manual_paused = bool(paused)
        if self.broadcaster:
            self.broadcaster.push_pause_threadsafe(self._is_paused())

    def is_manual_paused(self) -> bool:
        return self._manual_paused

    def _is_fullscreen_pause_enabled(self) -> bool:
        with self.config_lock:
            return bool(self.config.get("fullscreenPause", True))

    def _get_bridge_state(self) -> dict:
        """Snapshot of bridge-scoped (non-per-screen) toggles the
        Configurator's System section binds to. Cheap — just a few
        dict lookups under the config lock.

        v1.5.0-beta: also echoes the nested config blocks the new
        per-screen sources + sACN output UI bind to. Deep-copied so
        the Configurator can mutate its local copy freely. (Caught
        as a v1.4.0-beta regression — the OpenRGB sub-section never
        reflected the persisted host/port because this method only
        returned the four flat toggles.)"""
        with self.config_lock:
            return {
                "fullscreenPause":      bool(self.config.get("fullscreenPause", True)),
                "updateCheckEnabled":   bool(self.config.get("updateCheckEnabled", True)),
                "allowBetas":           bool(self.config.get("allowBetas", False)),
                "presetHotkeysEnabled": bool(self.config.get("presetHotkeysEnabled", False)),
                # v2.4.4-beta.19: the stored preference ("auto"/"en"/"de"),
                # not the resolved language. The picker has to show what
                # the user chose — echoing _CURRENT_LANG would turn
                # "Automatic" into "German" the moment it round-trips.
                "language":             str(self.config.get("language") or "auto"),
                "openrgbOutput": copy.deepcopy(self.config.get("openrgbOutput") or {}),
                # v1.6.2-beta: SDK-server config block surfaced to the
                # Configurator so the Integrations card can render the
                # toggle + port + matrix dims out of the same shape.
                "openrgbSdkServer": copy.deepcopy(
                    self.config.get("openrgbSdkServer") or {}),
                "sources":       copy.deepcopy(self.config.get("sources") or {}),
                "sacnOutput":    copy.deepcopy(self.config.get("sacnOutput") or {}),
                # v1.5.0-beta: MQTT bridge config + the REST API token.
                # Password sanitised so a Configurator screenshot
                # doesn't accidentally leak the broker creds.
                "mqttBridge":    _redact_mqtt(self.config.get("mqttBridge") or {}),
                "apiToken":      str(self.config.get("apiToken") or ""),
                # v2.3.1: app version + cached release-notes for the
                # auto-popup "What's new" modal. lastSeenAppVersion
                # round-trips so the Configurator can compare against
                # APP_VERSION and decide whether to fire the modal.
                "appVersion":           APP_VERSION,
                "lastSeenAppVersion":   str(self.config.get("lastSeenAppVersion", "")),
                "releaseNotes":         _release_notes_for(APP_VERSION),
                "releaseNotesUrl":      ("https://github.com/Delido/signalrgb-wallpaper/"
                                          "releases/tag/v" + APP_VERSION),
                "changelogUrl":         ("https://github.com/Delido/signalrgb-wallpaper/"
                                          "blob/main/CHANGELOG.md"),
            }

    def _on_fullscreen_state(self, paused: bool):
        # Called from the watcher thread when fullscreen-active flips.
        # Push the COMBINED state so a manual pause isn't cleared when
        # a fullscreen app leaves the foreground.
        self._paused = bool(paused)
        if self.broadcaster:
            self.broadcaster.push_pause_threadsafe(self._is_paused())

    @staticmethod
    def _sniff_bg_ext(data: bytes) -> str:
        """Magic-byte → file extension for a screen-background upload.
        v1.2.6: pre-v1.2.6 every upload was saved as `.png` regardless
        of content. A video uploaded as a screen bg therefore landed as
        `screen-N-<ms>.png` holding MP4 bytes — and the wallpaper page's
        VIDEO_BG_EXTS detection keys off the URL extension, so it never
        recognised the file as a video and tried to render it as a still
        image. Sniffing the real container + saving the right extension
        is what makes video screen-backgrounds actually play."""
        if data[:8] == b"\x89PNG\r\n\x1a\n":                  return ".png"
        if data[:3] == b"\xff\xd8\xff":                        return ".jpg"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":      return ".webp"
        if data[:6] in (b"GIF87a", b"GIF89a"):                 return ".gif"
        if data[:4] == b"\x1aE\xdf\xa3":                       return ".webm"
        if len(data) > 12 and data[4:8] == b"ftyp":
            sub = data[8:12]
            if   sub == b"qt  ":                               return ".mov"
            elif sub.startswith(b"M4V"):                       return ".m4v"
            else:                                              return ".mp4"
        return ".png"   # default — the builder always sends PNG

    def _update_background(self, screen: int, png_bytes: bytes) -> bool:
        """Persist an uploaded background + point the screen's bgImage
        at it. Unique-timestamped filename so the wallpaper page sees a
        new URL and refetches (avoids stale-cache hits). Old
        screen-N-* files (any extension) are deleted so the screens/
        folder doesn't bloat over many edits.

        v1.2.6: the file extension is now sniffed from the bytes
        (image OR video container) instead of hard-coded `.png`, so
        video backgrounds get a `.mp4` / `.webm` / … name the wallpaper
        page recognises and plays through its <video> element.

        Note: called from the asyncio loop's HTTP handler with sync
        file I/O. PNG writes are small; a video write can be tens of
        MB but uploads are infrequent (one per Apply), so the brief
        loop block is acceptable vs. thread-pool overhead."""
        if self._block_if_mirror(screen, "background-upload"):
            return False
        try:
            millis = int(time.time() * 1000)
            ext = self._sniff_bg_ext(png_bytes)
            target = screens_dir() / f"screen-{screen}-{millis}{ext}"
            target.write_bytes(png_bytes)
            # Delete every prior screen-N-* file regardless of extension
            # (a screen could switch from a .png still to a .mp4 video).
            for old in screens_dir().glob(f"screen-{screen}-*"):
                if old != target and old.is_file():
                    try: old.unlink()
                    except OSError: pass
            with self.config_lock:
                self.config["screens"][str(screen)]["bgImage"] = str(target)
                # v1.2.14: a manual background upload re-arms the
                # auto-cycle clock so the cycle doesn't immediately
                # roll back to whatever was scheduled. Without this,
                # uploading a custom background to a cycle-enabled
                # screen would silently get overwritten on the next
                # CycleScheduler tick.
                cycle = self.config["screens"][str(screen)].get("cycle")
                if isinstance(cycle, dict):
                    cycle["lastApplyMs"] = int(time.time() * 1000)
                cfg_snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(cfg_snapshot)
            except Exception as e:
                print(f"[bg] save_config failed: {e}")
            print(f"[bg] screen={screen} saved {target.name} ({len(png_bytes)} bytes)")
            # Replicate the new bgImage path to every mirroring screen.
            # The PNG file itself is shared (mirrors point at the same
            # screen-N-*.png), so no per-mirror copy is needed.
            self._replicate_to_mirrors(screen)
            return True
        except Exception as e:
            print(f"[bg] update failed: {e}")
            return False

    def push_settings(self, screen: int, settings: dict):
        if self.broadcaster:
            self.broadcaster.push_settings_threadsafe(screen, settings)

    # ── Mirror replication helpers ───────────────────────────────────────
    # Any time a per-screen mutation runs against a screen that has
    # mirrors, the same change has to land on each mirror so the
    # invariant "mirror == source" holds. Single-key changes use the
    # cheaper key path; widget-array / preset / background changes use
    # the full snapshot path because the mutation isn't a single
    # key-value pair.

    def _block_if_mirror(self, screen: int, what: str) -> bool:
        if self._is_mirror(screen):
            print(f"[mirror] screen {screen} is a mirror; ignoring {what}")
            return True
        return False

    def _replicate_to_mirrors(self, source: int) -> None:
        """Copy every mirrorable key from `source` into each screen
        mirroring it, then push the new settings to those mirrors' WS
        clients. Used after widget-array mutations and background
        uploads where a single-key replicate isn't enough."""
        mirrors = self._get_mirrors_of(source)
        if not mirrors:
            return
        with self.config_lock:
            src = self.config.get("screens", {}).get(str(source))
            if not isinstance(src, dict):
                return
            src_copy = json.loads(json.dumps(src))
        for m in mirrors:
            def mutate(s, sc=src_copy):
                for k, v in sc.items():
                    if k in _NON_MIRRORED_KEYS:
                        continue
                    s[k] = v
            snap = self._mutate_screen(m, mutate)
            if snap is not None:
                self.push_settings(m, snap)

    # ── Widget CRUD ──────────────────────────────────────────────────────
    # All four entry points share the same shape: mutate the in-memory
    # config under config_lock, write it to disk, then push the fresh
    # settings to every WS client on the affected screen so the wallpaper
    # page re-renders. Tray controls and wallpaper-page drag both flow
    # through these.

    def _mutate_screen(self, screen: int, mutator) -> dict | None:
        """Apply `mutator(screen_dict)` under lock, persist, return a snapshot
        of the new screen settings. Returns None if the screen index is bad."""
        with self.config_lock:
            screens = self.config.get("screens", {})
            s = screens.get(str(screen))
            if s is None:
                return None
            mutator(s)
            snapshot   = json.loads(json.dumps(s))
            full_snap  = json.loads(json.dumps(self.config))
        try:
            save_config(full_snap)
        except Exception as e:
            print(f"[widgets] save_config failed: {e}")
        return snapshot

    def add_widget(self, screen: int, widget_type: str,
                   x: int | None = None, y: int | None = None,
                   w: int | None = None, h: int | None = None,
                   options: dict | None = None) -> dict | None:
        # v1.5.0-beta plugin API: widget types of the form
        # "plugin/<name>" are looked up dynamically from the plugin
        # registry. Defaults come from the plugin's manifest (label,
        # size, options), so a plugin can ship with sensible initial
        # values without our static catalogue knowing about it.
        defaults = None
        if widget_type.startswith("plugin/"):
            reg = getattr(self, "plugin_registry", None)
            plug_name = widget_type.split("/", 1)[1]
            plug = reg.get(plug_name) if reg else None
            if plug is None:
                print(f"[widgets] unknown plugin: {plug_name!r}")
                return None
            size = plug.get("defaultSize") or {}
            defaults = {
                "x": 60, "y": 60,
                "w": int(size.get("w") or 320),
                "h": int(size.get("h") or 200),
                "options": dict(plug.get("defaultOptions") or {}),
                "label": plug.get("label") or plug_name,
            }
        elif widget_type in WIDGET_DEFAULTS:
            defaults = WIDGET_DEFAULTS[widget_type]
        else:
            print(f"[widgets] unknown type: {widget_type!r}")
            return None
        if self._block_if_mirror(screen, "widget-add"): return None

        def mutate(s):
            existing = s.setdefault("widgets", [])
            # v1.2.13: per-screen monotonic counter persisted in
            # config so IDs stay collision-free even when two screens
            # rapid-add widgets in the same millisecond (Quick Looks
            # was a real culprit). Falls back to the ms-time scheme
            # only when the counter is missing for some reason.
            counter = int(s.get("_widgetIdSeq", 0)) + 1
            s["_widgetIdSeq"] = counter
            new_id = f"w_s{screen}_{counter}"
            # Merge bundle options over defaults so callers (Look bundles)
            # can override just the fields they care about; everything else
            # stays at the type's defaults.
            merged_opts = dict(defaults["options"])
            if isinstance(options, dict):
                merged_opts.update(options)
            entry = {
                "id":      new_id,
                "type":    widget_type,
                "x":       defaults["x"] if x is None else int(x),
                "y":       defaults["y"] if y is None else int(y),
                "w":       defaults["w"] if w is None else int(w),
                "h":       defaults["h"] if h is None else int(h),
                "options": merged_opts,
            }
            existing.append(entry)
            # Adding a widget via the "Add widget" button (no
            # explicit position) implicitly unlocks the page so the
            # user can find / move the freshly-added one. Bundle adds
            # come with explicit x/y/w/h already, so leave the lock
            # state alone in that path — Quick Looks should land in
            # a clean read-mode, not edit-mode.
            if x is None and y is None:
                s["widgetsLocked"] = False

        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
        return snap

    def remove_widget(self, screen: int, widget_id: str) -> dict | None:
        if self._block_if_mirror(screen, "widget-remove"): return None
        def mutate(s):
            s["widgets"] = [w for w in s.get("widgets", []) if w.get("id") != widget_id]
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
        return snap

    def quick_look_apply(self, screen: int,
                         snapshot_slot=None, settings=None, widgets=None) -> dict | None:
        """v1.2.16: atomic Quick Look apply. All three sub-ops
        (snapshot current state → preset slot, replace widget array,
        merge non-bg settings) happen inside one _mutate_screen call
        so they share a single config_lock acquisition. Pre-v1.2.16
        each was its own WS message → its own worker thread → its own
        lock acquire, and the bridge's free-threaded dispatch meant
        the snapshot could land AFTER the bundle's setting-updates
        had already mutated the live state, capturing post-bundle
        mixed state instead of pre-bundle."""
        if self._block_if_mirror(screen, "quick-look-apply"): return None
        if not isinstance(settings, dict): settings = {}
        if not isinstance(widgets, list):  widgets  = []
        # Strict slot range — fall back to no-snapshot if the caller
        # passed something silly.
        try:
            slot = int(snapshot_slot) if snapshot_slot is not None else -1
        except (TypeError, ValueError):
            slot = -1
        def mutate(s):
            # 1. Snapshot CURRENT state to the slot if requested.
            if 0 <= slot < PRESET_SLOTS:
                snapshot = {k: copy.deepcopy(s.get(k, DEFAULT_SCREEN_SETTINGS.get(k)))
                            for k in PRESET_SNAPSHOT_KEYS}
                # v1.6.1-beta R2.2: cycle sub-keys (user-config only)
                # so later Apply doesn't reset rotation runtime state.
                live_cycle = s.get("cycle") or {}
                default_cycle = DEFAULT_SCREEN_SETTINGS["cycle"]
                snapshot["cycle"] = {
                    k: copy.deepcopy(live_cycle.get(k, default_cycle.get(k)))
                    for k in PRESET_CYCLE_SUBKEYS
                }
                presets = list(s.get("presets") or [None] * PRESET_SLOTS)
                while len(presets) < PRESET_SLOTS:
                    presets.append(None)
                presets[slot] = snapshot
                s["presets"] = presets
            # 2. Apply non-widget settings. Bridge-side whitelist
            # mirrors what setting-update would accept; unknown keys
            # are ignored. monitorSetup goes through the dedicated
            # sanitiser to keep its invariants.
            for key, value in settings.items():
                if key not in BridgeRuntime._SETTABLE_SCREEN_KEYS:
                    continue
                if key in ("widgets", "mirrorOf", "cycle"):
                    # widgets is handled below; mirror toggle + cycle
                    # need their own dispatch paths — not safe to
                    # cram into a Quick Look.
                    continue
                # v1.2.12: hardware-perf preferences (gridRenderer,
                # glassQuality) belong to the user, not the bundle —
                # a "Cyberpunk Vibes" Look should not flip the DOM/
                # Canvas renderer or kill the glass blur because the
                # bundle author happened to have a strong CPU.
                if key in BridgeRuntime._BUNDLE_FORBIDDEN_KEYS:
                    continue
                if key == "monitorSetup":
                    value = BridgeRuntime._sanitise_monitor_setup(value)
                s[key] = value
            # 3. Replace widgets atomically.
            counter = int(s.get("_widgetIdSeq", 0))
            built = []
            for raw in widgets:
                if not isinstance(raw, dict): continue
                wt = str(raw.get("type") or "")
                if wt not in WIDGET_DEFAULTS:
                    continue
                defaults = WIDGET_DEFAULTS[wt]
                counter += 1
                merged_opts = dict(defaults["options"])
                if isinstance(raw.get("options"), dict):
                    merged_opts.update(raw["options"])
                built.append({
                    "id":      f"w_s{screen}_{counter}",
                    "type":    wt,
                    "x":       defaults["x"] if raw.get("x") is None else int(raw["x"]),
                    "y":       defaults["y"] if raw.get("y") is None else int(raw["y"]),
                    "w":       defaults["w"] if raw.get("w") is None else int(raw["w"]),
                    "h":       defaults["h"] if raw.get("h") is None else int(raw["h"]),
                    "options": merged_opts,
                })
            s["widgets"] = built
            s["_widgetIdSeq"] = counter
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
        return snap

    def replace_widgets(self, screen: int, incoming) -> dict | None:
        """v1.2.16: atomically replace the screen's widgets array with
        the bundle-provided list. Each incoming entry must carry a
        `type`; the bridge assigns IDs (so client-side ID collisions
        can't happen) and merges options with the type's defaults the
        same way `add_widget` does. Geometry (x/y/w/h) falls back to
        the type's defaults when missing. Used by Quick Looks apply
        and any future "import preset" flow."""
        if self._block_if_mirror(screen, "widgets-set"): return None
        if not isinstance(incoming, list):
            print("[widgets-set] payload must be a list")
            return None
        def mutate(s):
            built = []
            counter = int(s.get("_widgetIdSeq", 0))
            for raw in incoming:
                if not isinstance(raw, dict): continue
                wt = str(raw.get("type") or "")
                if wt not in WIDGET_DEFAULTS:
                    print(f"[widgets-set] skip unknown type: {wt!r}")
                    continue
                defaults = WIDGET_DEFAULTS[wt]
                counter += 1
                merged_opts = dict(defaults["options"])
                if isinstance(raw.get("options"), dict):
                    merged_opts.update(raw["options"])
                built.append({
                    "id":      f"w_s{screen}_{counter}",
                    "type":    wt,
                    "x":       defaults["x"] if raw.get("x") is None else int(raw["x"]),
                    "y":       defaults["y"] if raw.get("y") is None else int(raw["y"]),
                    "w":       defaults["w"] if raw.get("w") is None else int(raw["w"]),
                    "h":       defaults["h"] if raw.get("h") is None else int(raw["h"]),
                    "options": merged_opts,
                })
            s["widgets"] = built
            s["_widgetIdSeq"] = counter
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
        return snap

    def update_widget(self, screen: int, widget_id: str, fields: dict) -> dict | None:
        if self._block_if_mirror(screen, "widget-update"): return None
        # Whitelist mutable fields — never let a wallpaper-page bug bleed
        # arbitrary keys into our config file.
        allowed = {"x", "y", "w", "h", "options"}
        def mutate(s):
            for entry in s.get("widgets", []):
                if entry.get("id") != widget_id:
                    continue
                for k in allowed:
                    if k not in fields:
                        continue
                    if k == "options" and isinstance(fields[k], dict):
                        entry.setdefault("options", {}).update(fields[k])
                    else:
                        entry[k] = fields[k]
                break
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
        return snap

    # ----- Preset slots -----

    def save_preset(self, screen: int, slot: int,
                    thumbnail: str | None = None) -> dict | None:
        """Capture the screen's current state into preset slot `slot`.
        The snapshot is a deep copy of every PRESET_SNAPSHOT_KEYS value,
        so later mutations to the live settings don't drift into the
        saved slot. `cycle` is special-cased so only the user-config
        sub-keys travel (runtime state stays live). When `thumbnail`
        is supplied (base64 data-URL from the configurator's synthetic
        renderer) it goes alongside the snapshot for the preset-slot
        button to render."""
        if not (0 <= slot < PRESET_SLOTS):
            print(f"[preset] bad slot: {slot}")
            return None
        def mutate(s):
            snapshot = {k: copy.deepcopy(s.get(k, DEFAULT_SCREEN_SETTINGS.get(k)))
                        for k in PRESET_SNAPSHOT_KEYS}
            # v1.6.1-beta R2.2: snapshot only the user-config slice of
            # `cycle` so applying a preset never resets `lastApplyMs` /
            # `nextIdx` back to the snapshot's frozen-in-time values.
            live_cycle = s.get("cycle") or {}
            default_cycle = DEFAULT_SCREEN_SETTINGS["cycle"]
            snapshot["cycle"] = {
                k: copy.deepcopy(live_cycle.get(k, default_cycle.get(k)))
                for k in PRESET_CYCLE_SUBKEYS
            }
            if thumbnail:
                snapshot["_thumb"] = thumbnail
            presets = list(s.get("presets") or [None] * PRESET_SLOTS)
            while len(presets) < PRESET_SLOTS:
                presets.append(None)
            presets[slot] = snapshot
            s["presets"] = presets
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            print(f"[preset] saved screen={screen} slot={slot}")
        return snap

    def apply_preset(self, screen: int, slot: int) -> dict | None:
        """Write a saved snapshot back into the screen's live settings.
        Whitelist the keys so a malformed slot can't sneak unexpected
        fields into the config."""
        if not (0 <= slot < PRESET_SLOTS):
            print(f"[preset] bad slot: {slot}")
            return None
        if self._block_if_mirror(screen, "preset-apply"): return None
        with self.config_lock:
            screen_cfg = self.config.get("screens", {}).get(str(screen))
            if not screen_cfg:
                return None
            presets = screen_cfg.get("presets") or []
            if slot >= len(presets) or presets[slot] is None:
                print(f"[preset] empty slot: screen={screen} slot={slot}")
                return None
            snapshot = copy.deepcopy(presets[slot])
        def mutate(s):
            for k in PRESET_SNAPSHOT_KEYS:
                if k in snapshot:
                    s[k] = snapshot[k]
            # v1.6.1-beta R2.2: merge the snapshot's `cycle` sub-keys
            # into the live cycle dict so runtime state (lastApplyMs /
            # nextIdx) survives Apply. Older snapshots without
            # `cycle` skip silently.
            if isinstance(snapshot.get("cycle"), dict):
                s.setdefault("cycle", dict(DEFAULT_SCREEN_SETTINGS["cycle"]))
                for k in PRESET_CYCLE_SUBKEYS:
                    if k in snapshot["cycle"]:
                        s["cycle"][k] = snapshot["cycle"][k]
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
            print(f"[preset] applied screen={screen} slot={slot}")
        return snap

    def clear_preset(self, screen: int, slot: int) -> dict | None:
        if not (0 <= slot < PRESET_SLOTS):
            return None
        def mutate(s):
            presets = list(s.get("presets") or [None] * PRESET_SLOTS)
            while len(presets) < PRESET_SLOTS:
                presets.append(None)
            presets[slot] = None
            s["presets"] = presets
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            print(f"[preset] cleared screen={screen} slot={slot}")
        return snap

    def set_widgets_locked(self, screen: int, locked: bool) -> dict | None:
        if self._block_if_mirror(screen, "widgets-lock"): return None
        def mutate(s):
            s["widgetsLocked"] = bool(locked)
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
        return snap

    # ── Profile rules CRUD ───────────────────────────────────────────────
    def _persist_profiles(self):
        """Save config + push every screen's current settings so any
        connected Configurator tab sees the new profile list (profiles
        ride in the settings payload as a top-level field)."""
        with self.config_lock:
            snapshot = json.loads(json.dumps(self.config))
        try:
            save_config(snapshot)
        except Exception as e:
            print(f"[profiles] save_config failed: {e}")
        # Re-push settings to every active screen so the Configurator
        # picks up the new profiles list on its current WS frame.
        for i in range(N_SCREENS):
            try:
                self.push_settings(i, snapshot["screens"][str(i)])
            except Exception:
                pass

    def add_profile(self, exe: str, label: str | None,
                    screen, preset_slot: int) -> dict | None:
        exe = (exe or "").strip().lower()
        if not exe:
            return None
        try:
            preset_slot = int(preset_slot)
        except (TypeError, ValueError):
            return None
        if not (0 <= preset_slot < PRESET_SLOTS):
            return None
        # Normalise screen target: None / "all" → null (= all screens),
        # otherwise integer 0..N-1.
        if screen in (None, "", "all"):
            screen_val = None
        else:
            try:
                n = int(screen)
                screen_val = n if 0 <= n < N_SCREENS else None
            except (TypeError, ValueError):
                screen_val = None
        rid = f"p_{int(time.time() * 1000) % 10_000_000}"
        rule = {
            "id":         rid,
            "enabled":    True,
            "exe":        exe,
            "label":      (label or "").strip() or exe,
            "screen":     screen_val,
            "presetSlot": preset_slot,
        }
        with self.config_lock:
            self.config.setdefault("profiles", []).append(rule)
        self._persist_profiles()
        return rule

    def update_profile(self, rid: str, fields: dict) -> dict | None:
        allowed = {"enabled", "exe", "label", "screen", "presetSlot"}
        target = None
        with self.config_lock:
            for r in self.config.get("profiles", []):
                if r.get("id") == rid:
                    target = r
                    break
            if target is None:
                return None
            for k, v in fields.items():
                if k not in allowed:
                    continue
                if k == "enabled":
                    target["enabled"] = bool(v)
                elif k == "exe":
                    target["exe"] = str(v or "").strip().lower()
                elif k == "label":
                    target["label"] = str(v or "").strip()
                elif k == "screen":
                    if v in (None, "", "all"):
                        target["screen"] = None
                    else:
                        try:
                            n = int(v)
                            target["screen"] = n if 0 <= n < N_SCREENS else None
                        except (TypeError, ValueError):
                            target["screen"] = None
                elif k == "presetSlot":
                    try:
                        n = int(v)
                        if 0 <= n < PRESET_SLOTS:
                            target["presetSlot"] = n
                    except (TypeError, ValueError):
                        pass
            updated = json.loads(json.dumps(target))
        self._persist_profiles()
        return updated

    def remove_profile(self, rid: str) -> bool:
        with self.config_lock:
            before = list(self.config.get("profiles", []))
            after = [r for r in before if r.get("id") != rid]
            if len(after) == len(before):
                return False
            self.config["profiles"] = after
        # If the removed rule was the currently-active one, ProfileWatcher's
        # next tick (empty match) will revert on its own.
        self._persist_profiles()
        return True

    # ── Backup + Restore ─────────────────────────────────────────────────
    def build_backup_zip(self) -> bytes:
        """Serialise every piece of user state worth re-installing into a
        single ZIP. Three roots:
          • `config.json` at the archive root
          • `library/*` — wallpapers + thumbs + library.json
          • `screens/*` — builder-uploaded backgrounds, one per screen
        Anything else under %LOCALAPPDATA%\\SignalRGBWallpaper is
        regenerated on demand and isn't worth carrying around."""
        import io, zipfile
        buf = io.BytesIO()
        with self.config_lock:
            cfg_snapshot = json.dumps(self.config, indent=2).encode("utf-8")
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("config.json", cfg_snapshot)
            lib = library_dir()
            if lib.exists():
                for p in lib.rglob("*"):
                    if p.is_file():
                        z.write(p, "library/" + p.relative_to(lib).as_posix())
            scr = screens_dir()
            if scr.exists():
                for p in scr.rglob("*"):
                    if p.is_file():
                        z.write(p, "screens/" + p.relative_to(scr).as_posix())
        return buf.getvalue()

    def restore_backup_zip(self, data: bytes) -> dict:
        """Replace the live config + library + screens contents from a
        previously-exported ZIP. Returns a small report dict so the
        caller can surface counts. Destructive: existing library and
        screens files NOT in the ZIP are kept (additive merge for files,
        full replace for config.json) — safer than nuking the folder
        when the user accidentally restores an old backup."""
        import io, zipfile
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise ValueError(f"not a zip: {e}")
        if "config.json" not in zf.namelist():
            raise ValueError("backup is missing config.json")

        # Validate config.json parses + has the version field we expect.
        with zf.open("config.json") as f:
            cfg_text = f.read().decode("utf-8")
        try:
            new_cfg = json.loads(cfg_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"config.json is not valid JSON: {e}")
        if not isinstance(new_cfg, dict) or "screens" not in new_cfg:
            raise ValueError("config.json is missing required keys")

        # Extract library/* and screens/* into their respective dirs.
        # Path-traversal guard: refuse anything that resolves outside
        # the target folder.
        lib_root = library_dir().resolve()
        scr_root = screens_dir().resolve()
        copied = {"library": 0, "screens": 0}
        for name in zf.namelist():
            if name in ("", "config.json") or name.endswith("/"):
                continue
            parts = name.split("/", 1)
            if len(parts) != 2:
                continue
            head, rel = parts
            if head == "library":
                target = (lib_root / rel).resolve()
                if not str(target).startswith(str(lib_root)):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                copied["library"] += 1
            elif head == "screens":
                target = (scr_root / rel).resolve()
                if not str(target).startswith(str(scr_root)):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                copied["screens"] += 1

        # Swap the live config in place. Persist + push to all clients.
        with self.config_lock:
            self.config.clear()
            self.config.update(new_cfg)
            snapshot = json.loads(json.dumps(self.config))
        try:
            save_config(snapshot)
        except Exception as e:
            print(f"[restore] save_config failed: {e}")
        # Rebuild library.json from the now-restored disk contents so
        # any catalogue drift gets fixed.
        try:
            _library_rebuild_catalogue(library_dir())
        except Exception as e:
            print(f"[restore] library rebuild failed: {e}")
        # Push every screen's new settings to connected wallpaper pages.
        for i in range(N_SCREENS):
            s = snapshot.get("screens", {}).get(str(i))
            if isinstance(s, dict):
                self.push_settings(i, s)
        return copied

    def get_health_status(self) -> dict:
        """Snapshot of "is the install actually working?" signals for
        the tray's System-status dialog. Cheap to compute — meant to
        be called on-demand from the dialog open path."""
        # SignalRGB plugin file. Windows redirects the Documents folder
        # to OneDrive on a lot of installs, so `Path.home() / "Documents"`
        # is *not* where Inno Setup's {userdocs} actually put the
        # plugin. Walk a list of candidate roots (registry Personal,
        # OneDrive paths, plain Documents) and pick the first one that
        # has the file — fall back to the registry-preferred path for
        # the "Open plugins folder" button when nothing matches.
        plugin_rel = Path("WhirlwindFX") / "Plugins" / "SignalRGB_Desktop_Wallpaper.js"
        candidate_roots = _candidate_documents_dirs()
        plugin_path = None
        for root in candidate_roots:
            fp = root / plugin_rel
            if fp.is_file():
                plugin_path = fp
                break
        if plugin_path is None and candidate_roots:
            plugin_path = candidate_roots[0] / plugin_rel
        plugin_present = bool(plugin_path and plugin_path.is_file())

        # SignalRGB.exe / SignalRgb / SignalRGBLauncher running.
        signalrgb_running = False
        try:
            for p in psutil.process_iter(["name"]):
                n = (p.info.get("name") or "").lower()
                if "signalrgb" in n:
                    signalrgb_running = True
                    break
        except Exception:
            pass

        # Wallpaper pages connected via WS (one per active monitor).
        # `client_roles` distinguishes the Configurator's own WS from
        # actual wallpaper pages — without it, the user sees their own
        # open Configurator tab counted, which is misleading.
        pages_connected = 0
        if self.broadcaster:
            try:
                roles = getattr(self.broadcaster, "client_roles", {}) or {}
                if roles:
                    pages_connected = sum(
                        1 for r in roles.values() if r == "wallpaper")
                else:
                    pages_connected = sum(
                        len(s) for s in self.broadcaster.clients_by_screen.values())
            except Exception:
                pass

        # LHM only matters if at least one Hardware Sensor widget exists.
        lhm_widget_present = False
        with self.config_lock:
            for s in self.config.get("screens", {}).values():
                if not isinstance(s, dict):
                    continue
                for w in s.get("widgets", []):
                    if isinstance(w, dict) and w.get("type") == "hardware-sensor":
                        lhm_widget_present = True
                        break
                if lhm_widget_present:
                    break
        lhm_online = False
        lhm_count = 0
        if self.hwmon is not None:
            try:
                snap = self.hwmon.get_snapshot()
                if isinstance(snap, dict):
                    lhm_count = len(snap)
                    lhm_online = lhm_count > 0
            except Exception:
                pass

        # v2.4.11: the two setup steps nothing automates and nothing
        # used to detect — and between them the most common way a
        # correct-looking install still shows a black screen.
        #
        #   frames_arriving  the user installed everything but never
        #                    dragged the "Desktop Wallpaper" device onto
        #                    the SignalRGB canvas. The WS is up, so the
        #                    wallpaper's standby card stays hidden and
        #                    the screen is simply black with no clue.
        #   pages_per_screen the wallpaper was never assigned to a
        #                    monitor in Lively / WE. `pages_connected`
        #                    existed but only as a total, which cannot
        #                    say WHICH screen is missing one.
        #
        # get_measured_fps() already exists for the Configurator's
        # frame-rate readout; this just asks it the health question.
        screen_count = 1
        try:
            screen_count = max(1, int(self._get_screen_count()))
        except Exception:
            pass
        pages_per_screen = []
        fps_per_screen = []
        for i in range(screen_count):
            n = 0
            if self.broadcaster:
                try:
                    n = len(self.broadcaster.clients_by_screen.get(i, ()) or ())
                except Exception:
                    pass
            pages_per_screen.append(n)
            f = 0.0
            try:
                prov = getattr(self.broadcaster, "udp_provider", None) if self.broadcaster else None
                if prov:
                    f = float(prov.get_measured_fps(i))
            except Exception:
                pass
            fps_per_screen.append(round(f, 1))
        frames_arriving = any(f > 0 for f in fps_per_screen)

        return {
            "plugin_present":    plugin_present,
            "plugin_path":       str(plugin_path) if plugin_path else "",
            "plugin_dir":        str(plugin_path.parent) if plugin_path else "",
            "signalrgb_running": signalrgb_running,
            "pages_connected":   pages_connected,
            "screen_count":      screen_count,
            "pages_per_screen":  pages_per_screen,
            "fps_per_screen":    fps_per_screen,
            "frames_arriving":   frames_arriving,
            "lhm_widget_present": lhm_widget_present,
            "lhm_online":        lhm_online,
            "lhm_count":         lhm_count,
        }

    def reset_screen(self, screen: int) -> dict | None:
        """Reset every mirrorable setting on this screen back to its
        DEFAULT_SCREEN_SETTINGS value. Per-screen physical attributes
        (viewport, mirrorOf, presets) are preserved — the user's
        monitor identity and saved snapshots aren't lost when they
        ask for a clean slate."""
        if self._block_if_mirror(screen, "reset-screen"): return None
        def mutate(s):
            for k, v in DEFAULT_SCREEN_SETTINGS.items():
                if k in _NON_MIRRORED_KEYS:
                    continue
                # Deep-copy mutable defaults so a later mutation doesn't
                # bleed into the global DEFAULT_SCREEN_SETTINGS template.
                s[k] = copy.deepcopy(v)
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            self._replicate_to_mirrors(screen)
            print(f"[reset] screen={screen} restored to defaults")
        return snap

    def reset_all_screens(self) -> int:
        """Reset every screen to defaults, after saving a copy of the
        config next to it.

        v2.4.4-beta.21. reset_screen() has existed for a while but only
        ever applied to one screen, reachable from that screen's own
        card — so recovering from a thoroughly mangled multi-screen
        setup meant repeating it per screen, and there was no single
        "put it back how it was" for someone who had lost track.

        Deliberately narrower than a factory reset: presets, per-app
        profiles, the image library and every bridge-level option
        (language, update checks, OpenRGB/sACN/MQTT) are untouched.
        Those are the things that are laborious to recreate, and none
        of them is what someone means by "the wallpaper looks wrong
        now".

        The backup is a plain copy of config.json rather than a full
        backup ZIP: the ZIP carries the whole image library, which can
        be hundreds of megabytes, and none of it is at risk here.
        Failing to write it does not block the reset — it is a safety
        net, not a precondition — but it is reported either way.
        """
        backup = None
        try:
            src = config_path()
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = src.with_name(f"config.before-reset-{stamp}.json")
            with self.config_lock:
                payload = json.dumps(self.config, indent=2)
            backup.write_text(payload, encoding="utf-8")
            print(f"[reset] config backed up to {backup}")
        except Exception as e:
            backup = None
            print(f"[reset] backup failed (continuing anyway): {e}")

        done = 0
        for sc in range(N_SCREENS):
            try:
                # Mirrored screens are skipped by reset_screen itself —
                # resetting one would immediately be overwritten by its
                # source, and _block_if_mirror already says so.
                if self.reset_screen(sc) is not None:
                    done += 1
            except Exception as e:
                print(f"[reset] screen={sc} failed: {e}")
        print(f"[reset] reset {done} screen(s) to defaults")
        return done

    # Keys the wallpaper page / configurator are allowed to set via the
    # generic `setting-update` WS command. Whitelisted so a buggy page
    # can't write arbitrary garbage into config.json — anything not on
    # this list is silently dropped (with a console warning).
    _SETTABLE_SCREEN_KEYS = {
        "bgImage", "bgImageUrl", "bgFit", "bgTileScale", "bgDim",
        "barLayout", "showBars", "glowStrength",
        "gridBlur", "stripesBlur", "barHeight", "barWidth",
        "gridRenderer", "glassQuality", "frameRate",
        # v1.6.3-beta: effect-canvas quality bucket (performance /
        # balanced / quality). Controls ambient + pixelfx + audio-glow
        # canvas backing resolution + DPR + frame cap. Missing from
        # the whitelist → wallpaper never sees the user's pick.
        "effectQuality",
        "showStatus",
        "ambientEffect", "ambientTint", "ambientDensity",
        "pixelfx", "parallax3d",
        "audioGlow", "audioGlowIntensity", "audioGlowTint",
        "widgetsLocked", "widgetTileStyle",
        # v1.6.0-beta: theme palette + stackable mouse-distortion
        # effects. Need to be on this whitelist or the Configurator's
        # setting-update messages get silently dropped by
        # update_screen_setting → nothing happens on the wallpaper.
        "widgetTheme", "mouseEffects",
        # Mirror toggle — special-cased in update_screen_setting below
        # because activation copies the source's state onto self.
        "mirrorOf",
        # Auto-cycle settings — partial-merge in _update_cycle below so
        # the configurator can send just `enabled` or `intervalMin`
        # without resetting `lastApplyMs`/`nextIdx`.
        "cycle",
        # v1.2.8: Builder Monitor-Setup. Sanitised in the setter below
        # so a malformed payload can't poison the config.
        "monitorSetup",
    }

    # v1.2.12: keys that are settable via setting-update / monitor-pref
    # paths but should NOT travel inside a Look bundle. A Quick Look
    # captures the *visual* identity of a screen ("Cyberpunk Vibes"); the
    # hardware-perf preferences below are user-owned and survive bundles.
    _BUNDLE_FORBIDDEN_KEYS = frozenset({
        "gridRenderer",
        "glassQuality",
        "frameRate",
    })

    @staticmethod
    def _sanitise_monitor_setup(value):
        """Coerce a Configurator-sent monitorSetup payload into the
        known shape {mode, orientations[]}. Unknown modes fall back
        to "single"; orientations are clipped to the tile count and
        normalised to landscape unless explicitly "portrait"."""
        if not isinstance(value, dict):
            return {"mode": "single", "orientations": ["landscape"]}
        mode = value.get("mode")
        if mode not in ("single", "span-h", "span-v"):
            mode = "single"
        tile_count = 1 if mode == "single" else 2
        raw = value.get("orientations")
        out = []
        if isinstance(raw, list):
            for item in raw:
                out.append("portrait" if item == "portrait" else "landscape")
        # Pad / clip to the mode's tile count.
        while len(out) < tile_count:
            out.append("landscape")
        out = out[:tile_count]
        # Single mode never carries a portrait flag — the tile IS the
        # bridge's reported viewport, no rotation applies.
        if mode == "single":
            out = ["landscape"]
        return {"mode": mode, "orientations": out}

    def _get_mirrors_of(self, source: int) -> list[int]:
        """Return every screen index whose `mirrorOf` currently points
        at `source`. Read-only — used by the propagation paths to know
        where to fan a settings change out to."""
        out = []
        with self.config_lock:
            screens = self.config.get("screens", {})
            for k, s in screens.items():
                try:
                    idx = int(k)
                except ValueError:
                    continue
                if idx == source:
                    continue
                if isinstance(s, dict) and s.get("mirrorOf") == source:
                    out.append(idx)
        return out

    def _is_mirror(self, screen: int) -> bool:
        with self.config_lock:
            s = self.config.get("screens", {}).get(str(screen))
            return bool(isinstance(s, dict) and s.get("mirrorOf") is not None)

    def update_screen_setting(self, screen: int, key: str, value) -> dict | None:
        if key not in self._SETTABLE_SCREEN_KEYS:
            print(f"[settings] ignoring non-whitelisted key: {key!r}")
            return None
        # Mirror toggle has its own path: validate target, copy snapshot,
        # and don't replicate the toggle itself to other screens.
        if key == "mirrorOf":
            return self._set_mirror_of(screen, value)
        # Cycle is a partial-merge to preserve scheduler bookkeeping
        # (lastApplyMs / nextIdx) across config changes.
        if key == "cycle":
            return self._update_cycle(screen, value)
        # monitorSetup gets sanitised before persisting so a malformed
        # payload (wrong mode string, wrong orientation list length)
        # can't poison the config or break the Builder reading it back.
        if key == "monitorSetup":
            value = self._sanitise_monitor_setup(value)
        # Mutations on a mirror are rejected at the bridge as a safety
        # net — the Configurator already disables UI controls, but a
        # stale tab or a future REST client mustn't be able to drift
        # a mirror away from its source.
        # monitorSetup is the one exception: it's in _NON_MIRRORED_KEYS
        # because it describes physical hardware (not display config),
        # so a mirror screen still owns its own layout declaration.
        if key != "monitorSetup" and self._is_mirror(screen):
            print(f"[settings] screen {screen} is a mirror; ignoring {key!r}")
            return None
        def mutate(s):
            s[key] = value
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            if key not in _NON_MIRRORED_KEYS:
                for m in self._get_mirrors_of(screen):
                    msnap = self._mutate_screen(m, lambda s, k=key, v=value: s.__setitem__(k, v))
                    if msnap is not None:
                        self.push_settings(m, msnap)
        return snap

    def _set_mirror_of(self, screen: int, value) -> dict | None:
        """Activate / deactivate Mirror mode on `screen`. Validates the
        target index (no self-mirror, no mirroring an existing mirror),
        then on activation copies every mirrorable key from the source
        into self before flipping the flag."""
        # null / None → deactivate. Just clear the flag; leave the
        # current snapshot in place so the user can resume editing
        # whatever the mirror left behind.
        if value is None or value == "" or value is False:
            def deactivate(s):
                s["mirrorOf"] = None
            snap = self._mutate_screen(screen, deactivate)
            if snap is not None:
                self.push_settings(screen, snap)
            return snap
        try:
            tgt = int(value)
        except (TypeError, ValueError):
            print(f"[mirror] bad target: {value!r}")
            return None
        if not (0 <= tgt < N_SCREENS):
            print(f"[mirror] target {tgt} out of range")
            return None
        if tgt == screen:
            print(f"[mirror] refusing self-mirror on screen {screen}")
            return None
        # Chained mirrors get messy fast (A mirrors B which mirrors C).
        # Reject the inner step so the user has to break the chain first.
        if self._is_mirror(tgt):
            print(f"[mirror] refusing to mirror screen {tgt} (already a mirror)")
            return None
        # Snapshot the source's settable state, then overwrite self with
        # it (minus the per-screen-private keys) and flip the flag.
        with self.config_lock:
            src = self.config.get("screens", {}).get(str(tgt))
            if not isinstance(src, dict):
                return None
            src_copy = json.loads(json.dumps(src))
        def activate(s):
            for k, v in src_copy.items():
                if k in _NON_MIRRORED_KEYS:
                    continue
                s[k] = v
            s["mirrorOf"] = tgt
        snap = self._mutate_screen(screen, activate)
        if snap is not None:
            self.push_settings(screen, snap)
        return snap

    _CYCLE_USER_FIELDS = ("enabled", "intervalMin", "pool", "order")
    # v1.6.1-beta library categories: "backgrounds" picks items
    # flagged Background or Both — Template-only items (Builder
    # source material) stay out of the rotation.
    _CYCLE_ALLOWED_POOLS  = {"all", "pinned", "backgrounds"}
    _CYCLE_ALLOWED_ORDERS = {"sequential", "random"}

    def _update_cycle(self, screen: int, value) -> dict | None:
        """Merge a partial cycle dict into the current settings without
        clobbering the scheduler's own bookkeeping (lastApplyMs,
        nextIdx). Validates pool / order against whitelists so a
        misbehaving client can't write garbage. When the user flips
        enabled on, we reset lastApplyMs to 0 so the very first cycle
        tick triggers immediately rather than waiting a full interval."""
        if not isinstance(value, dict):
            return None
        def mutate(s):
            cur = s.get("cycle") or {}
            if not isinstance(cur, dict):
                cur = {}
            # Start from a fresh deep-copy of defaults to handle older
            # configs that never had cycle at all.
            base = copy.deepcopy(DEFAULT_SCREEN_SETTINGS["cycle"])
            base.update(cur)
            # Only merge user-settable fields; reject anything else.
            was_enabled = bool(base.get("enabled", False))
            for k in self._CYCLE_USER_FIELDS:
                if k not in value:
                    continue
                v = value[k]
                if k == "enabled":
                    base["enabled"] = bool(v)
                elif k == "intervalMin":
                    try:
                        base["intervalMin"] = max(1, min(720, int(v)))
                    except (TypeError, ValueError):
                        pass
                elif k == "pool":
                    if isinstance(v, str) and v in self._CYCLE_ALLOWED_POOLS:
                        base["pool"] = v
                elif k == "order":
                    if isinstance(v, str) and v in self._CYCLE_ALLOWED_ORDERS:
                        base["order"] = v
            # If the user just turned cycling on, kick the first tick
            # immediately by zeroing lastApplyMs.
            if base["enabled"] and not was_enabled:
                base["lastApplyMs"] = 0
            s["cycle"] = base
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
        return snap

    # Whitelist of global (bridge-scoped) keys the Configurator may set via
    # the `bridge-setting-update` WS command. Per-screen keys go through
    # `update_screen_setting` above; this is the global counterpart.
    _SETTABLE_BRIDGE_KEYS = {
        "screenCount", "presetHotkeysEnabled",
        # v1.2.1: tray-Advanced toggles migrated into the Configurator
        # System section. Same persisted keys the tray was already
        # writing — no new defaults / migration needed.
        "fullscreenPause", "updateCheckEnabled", "allowBetas",
        # v1.4.0-beta: whole OpenRGB-output sub-dict travels as a
        # single key. The handler below unpacks + validates the inner
        # leaves so a malformed Configurator push can't poison the
        # config.
        "openrgbOutput",
        # v1.5.0-beta: per-screen source picker + sACN output channel.
        # Both travel as their full sub-dict — same validation pattern
        # as openrgbOutput.
        "sources", "sacnOutput",
        # v1.5.0-beta: MQTT bridge config block.
        "mqttBridge",
        # v1.6.2-beta: OpenRGB-SDK server config block. Carries enabled
        # + host + port + per-screen matrix dims. Without the
        # whitelist entry the WS dispatch above silently drops every
        # setting-update for this key — symptom: clicking the Enabled
        # toggle in the Configurator does nothing.
        "openrgbSdkServer",
        # v2.3.1: bare version string the Configurator writes after
        # dismissing the "What's new" modal. Stored so the modal
        # doesn't re-fire on every Configurator open after the user
        # has seen the current version's notes.
        "lastSeenAppVersion",
        # v2.4.4-beta.19: UI language. The config field and the whole
        # i18n machinery have existed since v1.x, but nothing could
        # write the field — no control in the Configurator, no tray
        # item — so the only way to pick a language was editing
        # config.json by hand. Reported as "es sollte einstellbar sein
        # ob man deutsch oder englisch haben will".
        "language",
    }

    def update_bridge_setting(self, key: str, value):
        """Mutate a top-level (non-per-screen) config field. Currently
        screenCount + presetHotkeysEnabled — the Configurator + tray
        use this to retire the legacy Tk dialog as the sole source
        of those knobs.

        Re-pushes every screen's settings so the live screenCount field
        in the settings payload propagates to all connected pages
        (and the Configurator's screen-count input stays in sync if
        multiple Configurator tabs are open)."""
        if key not in self._SETTABLE_BRIDGE_KEYS:
            print(f"[settings] ignoring non-whitelisted bridge key: {key!r}")
            return
        if key == "screenCount":
            try:
                n = max(1, min(N_SCREENS, int(value)))
            except (TypeError, ValueError):
                print(f"[settings] screenCount value not an int: {value!r}")
                return
            with self.config_lock:
                if self.config.get("screenCount") == n:
                    return
                self.config["screenCount"] = n
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            for s in range(N_SCREENS):
                try:
                    self.push_settings(s, snapshot["screens"][str(s)])
                except Exception as e:
                    print(f"[settings] push after screenCount failed: {e}")
            # v1.6.2-beta: rebuild the SDK-server device list so any
            # connected OpenRGB GUI sees the updated count on next
            # reconnect. replace_devices() drops current clients so
            # they re-enumerate against the fresh descriptor.
            try:
                if getattr(self, "openrgb_sdk", None) is not None:
                    self.openrgb_sdk.reload()
            except Exception as e:
                print(f"[settings] openrgb-sdk reload after screenCount failed: {e}")
            print(f"[settings] screenCount -> {n}")
        elif key == "presetHotkeysEnabled":
            enabled = bool(value)
            with self.config_lock:
                if bool(self.config.get("presetHotkeysEnabled", False)) == enabled:
                    return
                self.config["presetHotkeysEnabled"] = enabled
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            # Spin the listener up or down to match. New listener
            # instance after a stop so the daemon thread can fully
            # terminate before we re-register the hotkeys.
            if enabled:
                if not self.hotkey_listener.is_running():
                    self.hotkey_listener.start()
            else:
                self.hotkey_listener.stop()
                self.hotkey_listener = HotkeyListener(self)
            print(f"[settings] presetHotkeysEnabled -> {enabled}")
        elif key == "lastSeenAppVersion":
            # v2.3.1: the Configurator writes APP_VERSION here after
            # dismissing the "What's new" modal so it doesn't re-fire
            # on the next page load. Just persist — no side effects.
            v = str(value or "").strip()
            with self.config_lock:
                if str(self.config.get("lastSeenAppVersion", "")) == v:
                    return
                self.config["lastSeenAppVersion"] = v
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            print(f"[settings] lastSeenAppVersion -> {v!r}")
        elif key == "language":
            # "auto" follows the OS; "en"/"de" pin it. Anything else is
            # dropped rather than persisted, so a malformed push cannot
            # leave the UI in a language with no translation table.
            lang = str(value or "auto").lower()
            if lang not in ("auto", "en", "de"):
                print(f"[settings] language value not recognised: {value!r}")
                return
            with self.config_lock:
                if self.config.get("language") == lang:
                    return
                self.config["language"] = lang
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            # Re-resolve immediately: _CURRENT_LANG drives tray labels,
            # the standby card and every t() call server-side, and a
            # restart to apply a language change would be absurd.
            init_language(snapshot)
            # Push settings so every open Configurator and wallpaper
            # page picks up the new language field on the same message
            # they already listen to.
            for sc in range(N_SCREENS):
                try:
                    self.push_settings(sc, snapshot["screens"][str(sc)])
                except Exception:
                    pass
            print(f"[settings] language -> {lang} (resolved: {_CURRENT_LANG})")
        elif key in ("fullscreenPause", "updateCheckEnabled", "allowBetas"):
            # Plain boolean settings the bridge consumes elsewhere
            # (fullscreen-watcher reads fullscreenPause every poll;
            # UpdateChecker reads updateCheckEnabled + allowBetas
            # before each scheduled check). No side-effects beyond
            # persisting + re-broadcasting — the consumer threads
            # pick up the change on their next iteration.
            enabled = bool(value)
            with self.config_lock:
                if bool(self.config.get(key, False)) == enabled:
                    return
                self.config[key] = enabled
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            # No screen-settings push needed — these are bridge-global.
            # The tray menu's checkbox state is re-read lazily on next
            # menu render so it stays in sync too.
            print(f"[settings] {key} -> {enabled}")
        elif key == "openrgbOutput":
            # v1.4.0-beta: validate + persist the OpenRGB output sub-
            # dict. The Configurator sends the whole block on every
            # toggle; we sanitise each leaf before commit so a typo'd
            # port can't disable the worker via TypeError later.
            if not isinstance(value, dict):
                print(f"[settings] openrgbOutput value not a dict: {type(value).__name__}")
                return
            try:
                # v1.5.0-beta spatial mapping: each device's normalised
                # (x, y) is validated + clamped here so a typo from
                # the Configurator can't push out-of-range floats into
                # the sampler.
                raw_mapping = value.get("deviceMapping") or {}
                if not isinstance(raw_mapping, dict):
                    raw_mapping = {}
                cleaned_mapping: dict[str, dict] = {}
                for dk, dv in raw_mapping.items():
                    try:
                        did = int(dk)
                        if not isinstance(dv, dict):
                            continue
                        x = max(0.0, min(1.0, float(dv.get("x", 0.5))))
                        y = max(0.0, min(1.0, float(dv.get("y", 0.5))))
                        entry: dict = {
                            "x": round(x, 4), "y": round(y, 4),
                        }
                        # v1.5.0-beta strip mode: optional line mapping.
                        # Recognised when `mode == "line"` AND both x2,
                        # y2 are present. Anything else collapses back to
                        # the v1.4-compatible point mode (single sample
                        # replicated across all LEDs).
                        mode = dv.get("mode")
                        if mode == "line" and "x2" in dv and "y2" in dv:
                            try:
                                x2 = max(0.0, min(1.0, float(dv["x2"])))
                                y2 = max(0.0, min(1.0, float(dv["y2"])))
                                entry["mode"] = "line"
                                entry["x2"] = round(x2, 4)
                                entry["y2"] = round(y2, 4)
                            except (TypeError, ValueError):
                                pass
                        cleaned_mapping[str(did)] = entry
                    except (TypeError, ValueError):
                        continue
                cleaned = {
                    "enabled":       bool(value.get("enabled", False)),
                    "host":          str(value.get("host") or "127.0.0.1")[:128],
                    "port":          max(1, min(65535, int(value.get("port") or 6742))),
                    "sourceScreen":  max(0, min(N_SCREENS - 1,
                                        int(value.get("sourceScreen") or 0))),
                    "deviceMapping": cleaned_mapping,
                }
            except (TypeError, ValueError) as e:
                print(f"[settings] openrgbOutput malformed: {e}")
                return
            with self.config_lock:
                prev = self.config.get("openrgbOutput") or {}
                if dict(prev) == cleaned:
                    return
                self.config["openrgbOutput"] = cleaned
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            # OpenRgbOutputManager re-reads its config each loop
            # iteration — no explicit kick needed; an enabled flip
            # is picked up within one second.
            print(f"[settings] openrgbOutput -> {cleaned}")
        elif key == "openrgbSdkServer":
            # v1.6.2-beta: SDK-server config. Same validate-and-persist
            # pattern as openrgbOutput; reload() is explicit because
            # the server lifecycle (TCP listen socket) needs to bind
            # to the new port immediately on enabled flip rather than
            # waiting for the next poll cycle.
            if not isinstance(value, dict):
                print(f"[settings] openrgbSdkServer value not a dict: "
                      f"{type(value).__name__}")
                return
            try:
                raw_matrix = value.get("matrix") or {}
                if not isinstance(raw_matrix, dict):
                    raw_matrix = {}
                cleaned_matrix: dict[str, list[int]] = {}
                for n in range(N_SCREENS):
                    m = raw_matrix.get(str(n)) or [32, 16]
                    if (not isinstance(m, (list, tuple)) or len(m) != 2
                            or not all(isinstance(v, int) and v > 0
                                        for v in m)):
                        m = [32, 16]
                    # Clamp to a sane range — matrix_size on the wire
                    # is uint16 (max 65535), and we encode 4 bytes per
                    # cell + 8-byte header, so absolute ceiling is
                    # ~16k cells. Pick 256×256 as a generous cap.
                    cleaned_matrix[str(n)] = [
                        max(1, min(256, int(m[0]))),
                        max(1, min(256, int(m[1]))),
                    ]
                cleaned = {
                    "enabled": bool(value.get("enabled", False)),
                    "host":    str(value.get("host") or "0.0.0.0")[:128],
                    "port":    max(1, min(65535,
                                int(value.get("port") or 6743))),
                    "matrix":  cleaned_matrix,
                }
            except (TypeError, ValueError) as e:
                print(f"[settings] openrgbSdkServer malformed: {e}")
                return
            with self.config_lock:
                prev = self.config.get("openrgbSdkServer") or {}
                if dict(prev) == cleaned:
                    return
                self.config["openrgbSdkServer"] = cleaned
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            # Explicit reload — the server's listen socket needs to
            # rebind / shut down based on the new enabled/port/matrix.
            try:
                if getattr(self, "openrgb_sdk", None) is not None:
                    self.openrgb_sdk.reload()
            except Exception as e:
                print(f"[settings] openrgb-sdk reload failed: {e}")
            print(f"[settings] openrgbSdkServer -> {cleaned}")
        elif key == "sources":
            # v1.5.0-beta: per-screen source picker. The Configurator
            # sends the whole `{screen_idx: {type, …}}` block on every
            # change; we validate per leaf so a typo can't poison the
            # routing table. Recognised types: signalrgb (default),
            # openrgb, sacn. Unknown types fall back to signalrgb.
            if not isinstance(value, dict):
                print(f"[settings] sources value not a dict: {type(value).__name__}")
                return
            cleaned: dict = {}
            for n in range(N_SCREENS):
                raw = value.get(str(n)) or value.get(n) or {}
                if not isinstance(raw, dict):
                    raw = {}
                t = raw.get("type") or "signalrgb"
                # v1.6.2-beta: "openrgb-sdk" added as a valid type so
                # users can route a screen's colour feed to the
                # SDK-server channel from the Configurator.
                if t not in ("signalrgb", "openrgb", "sacn", "openrgb-sdk"):
                    t = "signalrgb"
                entry = {"type": t}
                if t == "openrgb":
                    try:
                        entry["host"] = str(raw.get("host") or "127.0.0.1")[:128]
                        entry["port"] = max(1, min(65535, int(raw.get("port") or 6742)))
                        entry["deviceIndex"] = max(0, int(raw.get("deviceIndex") or 0))
                    except (TypeError, ValueError):
                        entry = {"type": "signalrgb"}
                elif t == "sacn":
                    try:
                        u = int(raw.get("universe") or 1)
                    except (TypeError, ValueError):
                        u = 1
                    entry["universe"] = max(1, min(63999, u))
                # openrgb-sdk has no per-screen extras — the server is
                # configured globally under config.openrgbSdkServer.
                cleaned[str(n)] = entry
            with self.config_lock:
                prev = self.config.get("sources") or {}
                if dict(prev) == cleaned:
                    return
                self.config["sources"] = cleaned
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            print(f"[settings] sources -> {cleaned}")
        elif key == "sacnOutput":
            # v1.5.0-beta: sACN output config block. Same shape-tolerant
            # pattern as openrgbOutput.
            if not isinstance(value, dict):
                print(f"[settings] sacnOutput value not a dict: {type(value).__name__}")
                return
            try:
                dest = str(value.get("destination") or "multicast")
                if dest not in ("multicast", "unicast"):
                    dest = "multicast"
                universes_in = value.get("universes") or {}
                if not isinstance(universes_in, dict):
                    universes_in = {}
                universes: dict[str, int] = {}
                for n in range(N_SCREENS):
                    try:
                        u = int(universes_in.get(str(n))
                                or universes_in.get(n)
                                or (n + 1))
                    except (TypeError, ValueError):
                        u = n + 1
                    universes[str(n)] = max(1, min(63999, u))
                cleaned = {
                    "enabled":     bool(value.get("enabled", False)),
                    "destination": dest,
                    "unicastHost": str(value.get("unicastHost") or "")[:128],
                    "priority":    max(0, min(200, int(value.get("priority") or 100))),
                    "universes":   universes,
                }
            except (TypeError, ValueError) as e:
                print(f"[settings] sacnOutput malformed: {e}")
                return
            with self.config_lock:
                prev = self.config.get("sacnOutput") or {}
                if dict(prev) == cleaned:
                    return
                self.config["sacnOutput"] = cleaned
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            print(f"[settings] sacnOutput -> {cleaned}")
        elif key == "mqttBridge":
            # v1.5.0-beta MQTT bridge — same shape-tolerant validation.
            if not isinstance(value, dict):
                print(f"[settings] mqttBridge value not a dict: {type(value).__name__}")
                return
            # Preserve the saved password when the incoming value is
            # the redacted sentinel ("***") — the Configurator never
            # sees the real password, so a settings-update that keeps
            # the field unchanged shouldn't wipe it.
            with self.config_lock:
                prev_pwd = str((self.config.get("mqttBridge") or {})
                                .get("password") or "")
            try:
                incoming_pwd = str(value.get("password") or "")
                if incoming_pwd in ("***", ""):
                    incoming_pwd = prev_pwd
                cleaned = {
                    "enabled":         bool(value.get("enabled", False)),
                    "host":            str(value.get("host") or "localhost")[:128],
                    "port":            max(1, min(65535, int(value.get("port") or 1883))),
                    "username":        str(value.get("username") or "")[:128],
                    "password":        incoming_pwd[:256],
                    "clientId":        str(value.get("clientId") or "signalrgb-wallpaper")[:64],
                    "topicPrefix":     str(value.get("topicPrefix") or "signalrgb-wallpaper")[:64],
                    "discoveryPrefix": str(value.get("discoveryPrefix")
                                            if value.get("discoveryPrefix") is not None
                                            else "homeassistant")[:64],
                }
            except (TypeError, ValueError) as e:
                print(f"[settings] mqttBridge malformed: {e}")
                return
            with self.config_lock:
                prev = self.config.get("mqttBridge") or {}
                if dict(prev) == cleaned:
                    return
                self.config["mqttBridge"] = cleaned
                snapshot = json.loads(json.dumps(self.config))
            try:
                save_config(snapshot)
            except Exception as e:
                print(f"[settings] save_config failed: {e}")
            print(f"[settings] mqttBridge -> {dict(cleaned, password='***')}")

    def _on_widget_command(self, screen: int, msg: dict):
        """Asyncio-thread callback bridging Broadcaster→BridgeRuntime. We
        defer the actual persistence + rebroadcast to a thread so the WS
        read loop never blocks on the config-file write."""
        def run():
            t = msg.get("type")
            if   t == "widget-update":
                fields = {k: msg[k] for k in ("x", "y", "w", "h", "options") if k in msg}
                self.update_widget(screen, str(msg.get("id", "")), fields)
            elif t == "widget-add":
                # widget-add gained optional x/y/w/h/options fields in
                # v1.2-dev for the Quick Looks bundle-apply path —
                # otherwise applying a 5-widget bundle would require
                # an add-then-update round-trip per widget. Existing
                # callers (the "Add widget" button) just pass
                # widgetType; backwards-compatible.
                self.add_widget(
                    screen,
                    str(msg.get("widgetType", "")),
                    x=msg.get("x"), y=msg.get("y"),
                    w=msg.get("w"), h=msg.get("h"),
                    options=msg.get("options"),
                )
            elif t == "widget-remove":
                self.remove_widget(screen, str(msg.get("id", "")))
            elif t == "widgets-set":
                # v1.2.16: atomic widget-array replace for Quick Looks.
                # Pre-v1.2.16 applyLookBundle did widget-remove × N
                # followed by widget-add × M as separate WS messages;
                # _on_widget_command spawns a worker thread per message
                # so the operations raced and bundle widgets ended up
                # interleaved with the old set. widgets-set wipes +
                # appends inside one mutate(s) call under the config
                # lock — no race.
                self.replace_widgets(screen, msg.get("widgets") or [])
            elif t == "quick-look-apply":
                # v1.2.16: all-in-one atomic Quick Look apply. Snapshot
                # the current state to a preset slot, replace widgets,
                # and set the bundle's non-widget settings — all under
                # one config_lock acquire so the auto-snapshot
                # captures the pre-bundle state regardless of which
                # threads race in. Earlier versions queued these as
                # three separate WS messages whose worker threads
                # raced.
                self.quick_look_apply(
                    screen,
                    snapshot_slot=msg.get("snapshotSlot"),
                    settings=msg.get("settings") or {},
                    widgets=msg.get("widgets") or [],
                )
            elif t == "widgets-lock":
                self.set_widgets_locked(screen, bool(msg.get("locked", True)))
            elif t == "setting-update":
                self.update_screen_setting(screen, str(msg.get("key", "")),
                                           msg.get("value"))
            elif t == "bridge-setting-update":
                self.update_bridge_setting(str(msg.get("key", "")),
                                           msg.get("value"))
            elif t == "system-action":
                # v1.2.1: Configurator System-section trigger for
                # the maintenance commands the tray's Advanced
                # submenu used to own. Whitelisted action → tray
                # method, so the same code paths run regardless of
                # entry point. tray is set by main() after both
                # bridge + tray exist; bail silently if not yet
                # ready (shouldn't happen in practice).
                action = str(msg.get("action", ""))
                # v1.5.0-beta: bridge-runtime actions (token regen,
                # plugin rescan, open plugins folder) live OUTSIDE
                # the tray namespace because they touch
                # config/registry state directly.
                if action == "reset-all-screens":
                    self.reset_all_screens()
                elif action == "regenerate-api-token":
                    new_tok = secrets.token_urlsafe(32)
                    with self.config_lock:
                        self.config["apiToken"] = new_tok
                        snap = json.loads(json.dumps(self.config))
                    try: save_config(snap)
                    except Exception as e:
                        print(f"[system-action] save_config failed: {e}")
                    # Push the fresh token to every connected client
                    # so the Configurator's display updates without
                    # waiting for the next periodic settings round.
                    for s in range(N_SCREENS):
                        try:
                            self.push_settings(s, self.get_settings(s))
                        except Exception:
                            pass
                    print(f"[system-action] API token regenerated")
                elif action == "rescan-plugins":
                    reg = getattr(self.broadcaster, "plugin_registry", None)
                    if reg is not None:
                        try:
                            reg.rescan()
                        except Exception as e:
                            print(f"[system-action] rescan-plugins failed: {e}")
                    for s in range(N_SCREENS):
                        try:
                            self.push_settings(s, self.get_settings(s))
                        except Exception:
                            pass
                    print(f"[system-action] plugins rescanned")
                elif action == "open-plugins-folder":
                    reg = getattr(self.broadcaster, "plugin_registry", None)
                    folder = str(reg.root) if reg else ""
                    if folder:
                        try:
                            os.makedirs(folder, exist_ok=True)
                            os.startfile(folder)
                        except Exception as e:
                            print(f"[system-action] open plugins: {e}")
                elif self.tray is None:
                    print(f"[system-action] tray not wired up — dropping {action!r}")
                else:
                    handler = {
                        "reload-config":     self.tray._reload_config,
                        "reload-wallpapers": self.tray._reload_wallpapers,
                        "reimport-bundles":  self.tray._reimport_bundles,
                        "check-updates-now": self.tray._check_updates_now,
                        "open-releases":     self.tray._open_update_page,
                        # v1.2.13: opens %LOCALAPPDATA%\SignalRGBWallpaper\library
                        # in Explorer so the user can drop several images at
                        # once / cleanup / inspect — same handler the tray
                        # menu uses but routed through the WS so a button
                        # in the Configurator can trigger it.
                        "open-library-folder": self.tray._open_library_folder,
                    }.get(action)
                    if handler is None:
                        print(f"[system-action] unknown action: {action!r}")
                    else:
                        try:
                            handler(None, None)
                            print(f"[system-action] dispatched {action}")
                        except Exception as e:
                            print(f"[system-action] {action} failed: {e}")
            elif t == "viewport":
                self.update_viewport(screen, msg.get("w"), msg.get("h"))
            elif t == "preset-save":
                thumb = msg.get("thumbnail")
                if not isinstance(thumb, str):
                    thumb = None
                self.save_preset(screen, int(msg.get("slot", -1)),
                                 thumbnail=thumb)
            elif t == "preset-apply":
                self.apply_preset(screen, int(msg.get("slot", -1)))
            elif t == "preset-clear":
                self.clear_preset(screen, int(msg.get("slot", -1)))
            elif t == "screen-reset":
                self.reset_screen(screen)
            elif t == "profile-add":
                self.add_profile(
                    exe        = str(msg.get("exe", "")),
                    label      = msg.get("label"),
                    screen     = msg.get("screen"),
                    preset_slot= int(msg.get("presetSlot", 0)))
            elif t == "profile-update":
                rid = str(msg.get("id", ""))
                if rid:
                    fields = {k: msg[k] for k in
                              ("enabled", "exe", "label", "screen", "presetSlot")
                              if k in msg}
                    self.update_profile(rid, fields)
            elif t == "profile-remove":
                rid = str(msg.get("id", ""))
                if rid:
                    self.remove_profile(rid)
        # v1.2.8: previously this spawned a fresh OS thread per WS
        # command. Builder per-tile drag + Quick Looks fire 60-100
        # widget-update messages per drag and Configurator sliders
        # likewise stream setting-update at high rate — over a 12 h
        # session that meant thousands of thread spawns. Windows
        # commits thread stack pages lazily but the high-water marks
        # accumulate in the process commit charge even after the
        # threads exit, plus each thread's run() closure pinned the
        # message dict + _mutate_screen's deep-copied config in heap
        # until the disk write completed. Submitting to the loop's
        # default ThreadPoolExecutor (~32 workers, recycled) keeps
        # the off-loop file-write isolation but caps thread count.
        self.loop.run_in_executor(None, run)

    def update_viewport(self, screen: int, w, h) -> dict | None:
        """Stash the wallpaper page's actual viewport size so the configurator
        can scale its layout preview to the real monitor. Skipped silently
        when the size already matches the persisted value so a stable
        connection doesn't write the config file every reconnect."""
        try:
            w = int(w)
            h = int(h)
        except (TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        with self.config_lock:
            s = self.config["screens"].get(str(screen))
            if s is None:
                return None
            if s.get("viewportW") == w and s.get("viewportH") == h:
                return None
        def mutate(s):
            s["viewportW"] = w
            s["viewportH"] = h
        snap = self._mutate_screen(screen, mutate)
        if snap is not None:
            self.push_settings(screen, snap)
            print(f"[viewport] screen={screen} {w}x{h}")
        return snap

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="bridge-asyncio").start()
        self._ready.wait()
        # Watcher runs on its own daemon thread; needs the asyncio loop
        # ready first so push_pause_threadsafe has a target.
        self.fullscreen_watcher.start()

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.broadcaster = Broadcaster(
            loop,
            self._get_settings,
            self._get_screen_count,
            self._update_background,
            self._is_paused,
            self._on_widget_command,
            self._get_bridge_state,
        )
        # System-stats poller pushes 1 Hz snapshots over the WS once the
        # broadcaster is up. No-op if psutil wasn't bundled into this build.
        # The HwMon poller starts even when LHM isn't running — it'll just
        # report `online: false` until the user starts LibreHardwareMonitor
        # with its Remote Web Server enabled.
        # v1.2.10: HwMon LHM poll only fires when a hardware-sensor
        # widget is placed somewhere. The Configurator's
        # /hwmon/sensors picker still works — when the user opens
        # the picker without a sensor widget placed we either
        # serve a stale snapshot (last successful poll) or "no
        # sensors". A "place a hardware-sensor widget first" UX
        # nudge would be nicer but is out of scope for the leak
        # hardening pass.
        self.hwmon = HwMonPoller(should_poll=self._poller_gate("hardware-sensor"))
        self.hwmon.start()
        # Let the broadcaster's /hwmon/sensors HTTP handler reach the
        # poller's snapshot + status. Set here rather than via __init__
        # so the broadcaster doesn't need to know about hwmon at all if
        # the user is on a build without it.
        self.broadcaster.hwmon_provider = self.hwmon
        # Expose the runtime so /backup and /restore HTTP handlers can
        # call back into config + persistence without needing the
        # methods passed individually through the constructor.
        self.broadcaster.bridge_runtime = self
        # Wallpaper-shuffle poller — wakes every 30 s and cycles each
        # screen whose `cycle.enabled` is true past its `intervalMin`.
        self.cycle_scheduler = CycleScheduler(self)
        self.cycle_scheduler.start()
        # Global Ctrl+Shift+1..4 → apply preset slot N on every screen.
        # Off by default; tray toggle flips it on. Stays in this attr
        # even when disabled so the toggle path is symmetrical.
        self.hotkey_listener = HotkeyListener(self)
        with self.config_lock:
            if bool(self.config.get("presetHotkeysEnabled", False)):
                self.hotkey_listener.start()
        # Per-app / per-game profiles — foreground-window watcher.
        # Runs unconditionally; the cost is one syscall per second and
        # the rules list defaults to empty so it's a no-op until the
        # user adds some.
        self.profile_watcher = ProfileWatcher(self)
        self.profile_watcher.start()
        # Windows SMTC poller — drains the "now playing" media session
        # so the now-playing widget can render whatever the user has
        # active (Spotify, Groove, browser HTML5 audio, etc.). No-op
        # when the winrt-Windows.Media.Control package isn't bundled.
        # v1.2.9-beta: hard-disable path. Skip *every* SMTC touchpoint
        # — no NowPlayingPoller instance, no winrt import, no thread,
        # no IPC. SysStatsPoller's `nowplaying=` is left None so its
        # 1 Hz JSON push omits the nowPlaying field entirely.
        if ENABLE_NOWPLAYING:
            # v1.2.10: SMTC poll only when a now-playing widget is
            # placed. With no such widget the entire
            # Bridge → NPSMSvc → Spotify → DWM → WebView2 cascade
            # the user observed in v1.2.6 stays cold even with the
            # wallpaper page running.
            self.nowplaying = NowPlayingPoller(should_poll=self._poller_gate("now-playing"))
            self.nowplaying.start()
        else:
            self.nowplaying = None
            print("[nowplaying] disabled by ENABLE_NOWPLAYING=False")
        # v1.2.10: SysStats is the carrier for hwmon + nowplaying
        # payloads as well as its own CPU/RAM/network samples, so
        # its gate is the union of every widget that reads any of
        # those fields. With none of them placed the bridge is
        # truly idle: no psutil collect, no WS push, no JSON encode.
        self.sysstats = SysStatsPoller(self.broadcaster,
                                       hwmon=self.hwmon,
                                       nowplaying=self.nowplaying,
                                       should_poll=self._poller_gate(
                                           "cpu-meter", "ram-meter",
                                           "hardware-sensor", "now-playing"))
        self.sysstats.start()
        # v1.4.0-beta: OpenRGB output channel. Default disabled; the
        # manager idles when its config flag is off, so wiring it up
        # unconditionally has zero cost for users who never opt in.
        # When enabled, the broadcaster's frame tap feeds averaged
        # RGB into the worker thread which pushes via the SDK.
        # v1.5.0-beta REST API: attach the runtime so /api/v1/* routes
        # can reach apply_preset / set_manual_pause / etc. without
        # threading new callbacks through Broadcaster.__init__.
        self.broadcaster.bridge_runtime = self
        self.openrgb = OpenRgbOutputManager(self)
        self.broadcaster.add_frame_tap(self.openrgb.on_frame)
        # /openrgb/status reaches the manager through the broadcaster
        # attribute the HTTP handler already has in scope. Mirrors the
        # hwmon_provider / udp_provider attachment pattern.
        self.broadcaster.openrgb_provider = self.openrgb
        self.openrgb.start()
        # v1.5.0-beta: per-screen source routing + the three new
        # input/output channels. SourceManager is constructed first
        # because the UdpReceiver inside _serve() needs it. The input
        # managers + sACN output emitter pull config from the bridge
        # directly so a runtime config change is picked up within one
        # poll interval — no explicit reload kick needed.
        self.source_mgr = SourceManager(self, self.broadcaster)
        self.broadcaster.source_provider = self.source_mgr
        self.openrgb_in = OpenRgbInputManager(self, self.source_mgr)
        self.broadcaster.openrgb_input_provider = self.openrgb_in
        self.openrgb_in.start()
        # v1.6.2-beta: OpenRGB-SDK *server* — exposes the bridge to
        # OpenRGB GUI / SDK clients as virtual matrix devices, one
        # per screen. Off until config.openrgbSdkServer.enabled is
        # flipped on in the Configurator's Integrations tab.
        self.openrgb_sdk = OpenRgbSdkServerManager(self)
        self.broadcaster.openrgb_sdk_provider = self.openrgb_sdk
        self.openrgb_sdk.start()
        self.sacn_in = SacnInputManager(self, self.source_mgr)
        self.broadcaster.sacn_input_provider = self.sacn_in
        self.sacn_in.start()
        self.sacn_out = SacnOutputManager(self)
        self.broadcaster.add_frame_tap(self.sacn_out.on_frame)
        self.broadcaster.sacn_output_provider = self.sacn_out
        self.sacn_out.start()
        # v1.5.0-beta MQTT bridge: same frame-tap-as-input pattern as
        # OpenRGB / sACN output, plus a publisher thread for slower
        # state topics (preset, pause, background). Stays idle until
        # mqttBridge.enabled is flipped on in the config.
        self.mqtt = MqttBridge(self)
        self.broadcaster.add_frame_tap(self.mqtt.on_frame)
        self.broadcaster.mqtt_provider = self.mqtt
        self.mqtt.start()
        # v1.5.0-beta plugin registry. Stateless except for the
        # scanned catalogue — rescan on demand via the Configurator
        # or by hitting /plugins. Stays alive even when no plugins
        # are installed so the API surface is consistent.
        self.plugin_registry = PluginRegistry()
        self.broadcaster.plugin_registry = self.plugin_registry
        self.broadcaster.plugin_provider = self.plugin_registry
        try:
            loop.run_until_complete(self._serve())
        except Exception as e:
            print(f"[bridge] crashed: {e}")
        finally:
            loop.close()

    async def _serve(self):
        ws_server = await asyncio.start_server(self.broadcaster.handle_client, WS_HOST, WS_PORT)
        udp_transport, udp_protocol = await self.loop.create_datagram_endpoint(
            lambda: UdpReceiver(self.broadcaster, self.source_mgr, self.loop),
            local_addr=(UDP_HOST, UDP_PORT),
        )
        # v1.2.12: hand the UdpReceiver to the broadcaster so /config
        # responses can include the per-screen measured plugin send
        # rate. The receiver tracks one 1 s sliding window per screen.
        self.broadcaster.udp_provider = udp_protocol
        # Keep a ref to the UdpReceiver so the heartbeat below can
        # read its partials count for diagnostics.
        self._udp_protocol = udp_protocol
        # v1.2.13: validate that every provider attribute the broadcaster
        # advertises is actually wired. These get attached one-by-one
        # from various startup paths (hwmon_provider from HwMonPoller
        # init, udp_provider above, …); a missed wiring used to fall
        # through silently — the picker just showed an empty list. Now
        # the bridge prints a loud `[init]` warning so a maintainer
        # spots the regression while developing.
        _expected_providers = ("hwmon_provider", "udp_provider")
        for attr in _expected_providers:
            if not getattr(self.broadcaster, attr, None):
                print(f"[init] WARNING broadcaster.{attr} is not wired — "
                      f"the dependent endpoint will return empty data")
        print("SignalRGB Wallpaper bridge — multi-screen + tray")
        print(f"  UDP listener: udp://{UDP_HOST}:{UDP_PORT}  (plugin -> bridge)")
        print(f"  WS server:    ws://{WS_HOST}:{WS_PORT}/?screen=N")
        print(f"  HTTP images:  http://{WS_HOST}:{WS_PORT}/image?path=<absolute path>")
        print(f"  Config:       {config_path()}")
        # v1.2.7: heap-fragmentation heartbeat. CPython's pymalloc
        # holds onto arenas allocated under bursty workloads even
        # after objects are freed; without a periodic forced GC the
        # process RSS drifts up over a multi-hour session driven by
        # 60 Hz × N_screens UDP frame churn even when our reachable
        # set stays bounded. A gc.collect() every 60 s nudges
        # generation-2 GC to release empty arenas back to the OS,
        # and a single log line surfaces the trend so the next
        # diagnostic export captures the curve.
        self.loop.create_task(self._diag_heartbeat())
        # v2.4.1: WS keepalive. Pings every client every 20 s and reaps
        # the ones that stopped answering — the server half of the
        # sleep/resume fix for the stuck "bridge offline" card (#2).
        self.loop.create_task(self.broadcaster._keepalive_loop())
        self._ready.set()
        async with ws_server:
            await ws_server.serve_forever()

    async def _diag_heartbeat(self):
        import gc
        try:
            import psutil  # type: ignore
            _proc = psutil.Process()
        except Exception:
            _proc = None
        # gc every 60 s; log line every 5 min so logs stay readable.
        tick = 0
        # v2.4.3: sleep/resume marker. Each iteration should take ~60 s
        # of wall-clock; if far more elapsed, the machine was suspended
        # in between. Windows does broadcast WM_POWERBROADCAST, but
        # catching it needs a message pump on a window handle, and this
        # loop already runs on the right cadence to spot the gap for
        # free. The marker anchors everything else in the log: issue #2
        # was a sleep/resume bug whose diagnosis started with "which of
        # these lines are from after the resume?", and nothing in the
        # log answered that.
        _last_wall = time.time()
        _RESUME_GAP_S = 120.0     # 2x the tick — well clear of scheduling jitter
        while True:
            try:
                await asyncio.sleep(60)
                now_wall = time.time()
                gap = now_wall - _last_wall
                _last_wall = now_wall
                if gap > _RESUME_GAP_S:
                    mins = int(gap // 60)
                    hrs, mins = divmod(mins, 60)
                    span = f"{hrs}h{mins:02d}m" if hrs else f"{mins}m"
                    try:
                        n_now = sum(len(s) for s in self.broadcaster.clients_by_screen.values())
                    except Exception:
                        n_now = -1
                    print(f"[power] resume detected — {span} gap "
                          f"(suspended or clock jump); clients={n_now}")
                gc.collect()
                tick += 1
                if tick % 5 == 0:
                    try:
                        rss_mb = (_proc.memory_info().rss / (1024 * 1024)) if _proc else 0.0
                    except Exception:
                        rss_mb = 0.0
                    try:
                        n_clients = sum(len(s) for s in self.broadcaster.clients_by_screen.values())
                    except Exception:
                        n_clients = 0
                    try:
                        n_tasks = sum(1 for t in asyncio.all_tasks(self.loop) if not t.done())
                    except Exception:
                        n_tasks = 0
                    try:
                        n_partials = len(getattr(self._udp_protocol, "partials", {}) or {})
                    except Exception:
                        n_partials = 0
                    print(f"[diag] rss={rss_mb:.1f}MB tasks={n_tasks} "
                          f"clients={n_clients} partials={n_partials}")
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"[diag] heartbeat error: {e}")


# ============================================================================
# Tkinter settings dialog
# ============================================================================

class SettingsDialog:
    """
    Modal-ish per-screen settings window. Built per invocation so we don't
    have to deal with re-showing a destroyed Tk root. Runs on whatever
    thread spawned it — we spawn it on a dedicated daemon thread so the
    pystray tray remains responsive.
    """

    def __init__(self, config: dict, on_save):
        self.config = config            # full config dict (we mutate in-place)
        self.on_save = on_save          # callback(updated_full_config: dict)
        self.root: tk.Tk | None = None
        # Per-screen tk Vars so we can read them back on Save.
        self.vars: list[dict[str, tk.Variable]] = []
        # Top-level (non-per-screen) Vars — currently just screenCount.
        self.global_vars: dict[str, tk.Variable] = {}
        # "Saved at HH:MM:SS" status label — updated on every Save click so
        # iterative tweaks (multi-screen tuning, image picker) have feedback
        # that the persist + push actually happened.
        self._saved_label: tk.Label | None = None

    def show(self):
        self.root = tk.Tk()
        self.root.title("SignalRGB Wallpaper — Settings")
        self.root.geometry("740x720")
        self.root.minsize(620, 540)

        # ── STICKY BOTTOM BUTTON BAR ───────────────────────────────────────
        # Packed FIRST with side="bottom" so it stays anchored even when the
        # notebook above scrolls or the window is resized small. Previous
        # layout could push the buttons off-screen on shorter windows.
        btn_bar = ttk.Frame(self.root)
        btn_bar.pack(side="bottom", fill="x", padx=12, pady=10)
        ttk.Button(btn_bar, text="Close", command=self._on_close).pack(side="right")
        ttk.Button(btn_bar, text="Save",  command=self._on_save).pack(side="right", padx=(0, 8))
        self._saved_label = ttk.Label(btn_bar, text="", foreground="#2a8a2a")
        self._saved_label.pack(side="left")

        # ── GLOBAL: SignalRGB device count ────────────────────────────────
        global_frame = ttk.LabelFrame(self.root, text="SignalRGB device count")
        global_frame.pack(fill="x", padx=12, pady=(12, 4))
        row1 = ttk.Frame(global_frame)
        row1.pack(fill="x", padx=10, pady=(10, 2))
        ttk.Label(row1, text="Number of screens:",
                  font=("Segoe UI", 9, "bold")).pack(side="left")
        sc_var = tk.IntVar(value=int(self.config.get("screenCount", 1)))
        self.global_vars["screenCount"] = sc_var
        ttk.Combobox(row1, textvariable=sc_var, values=[1, 2, 3],
                     state="readonly", width=4).pack(side="left", padx=(8, 0))
        ttk.Label(
            global_frame,
            text="How many virtual 'Desktop Wallpaper' devices SignalRGB exposes. "
                 "Each gets its own canvas slot in SignalRGB's Layouts view, so "
                 "different monitors can be driven with different colours pulled "
                 "from one SignalRGB effect.",
            foreground="#666", font=("Segoe UI", 9), wraplength=680, justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 10))

        # ── GLOBAL: Auto-pause ────────────────────────────────────────────
        autopause_frame = ttk.LabelFrame(self.root, text="Auto-pause")
        autopause_frame.pack(fill="x", padx=12, pady=(0, 4))
        fs_var = tk.BooleanVar(value=bool(self.config.get("fullscreenPause", True)))
        self.global_vars["fullscreenPause"] = fs_var
        ttk.Checkbutton(
            autopause_frame,
            text="Pause glow when a fullscreen application is active",
            variable=fs_var,
        ).pack(anchor="w", padx=10, pady=(10, 0))
        ttk.Label(
            autopause_frame,
            text="Detects fullscreen games, video players, and RDP sessions. "
                 "The glow freezes on its last drawn colours, CPU is saved, and "
                 "playback resumes within ~1 second when you leave fullscreen.",
            foreground="#666", font=("Segoe UI", 9), wraplength=680, justify="left",
        ).pack(anchor="w", padx=30, pady=(0, 10))

        # ── PER-SCREEN NOTEBOOK (each tab is independently scrollable) ───
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        for n in range(N_SCREENS):
            tab = ttk.Frame(notebook)
            notebook.add(tab, text=f"Screen {n+1}")
            scrollable = self._make_scrollable(tab)
            self.vars.append(self._build_tab(scrollable, n))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # -- helpers -----------------------------------------------------------

    def _make_scrollable(self, parent: ttk.Frame) -> ttk.Frame:
        """Wrap a notebook tab's content in a vertically-scrollable Canvas.
        Returns the inner Frame to add controls into. The classic tk
        scroll trick: Canvas + Scrollbar + Frame-in-create_window, with
        <Configure> bindings to keep scrollregion and width in sync."""
        canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(canvas_window, width=e.width))

        # Mouse wheel — bind only while the pointer is inside this canvas
        # so other widgets on the page still get their own wheel events.
        def _bind_wheel(_e):
            canvas.bind_all("<MouseWheel>",
                            lambda ev: canvas.yview_scroll(int(-1 * (ev.delta / 120)), "units"))
        def _unbind_wheel(_e):
            canvas.unbind_all("<MouseWheel>")
        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)
        inner.bind("<Enter>", _bind_wheel)
        inner.bind("<Leave>", _unbind_wheel)

        return inner

    def _setting_block(self, parent, label: str, build_control, help_text: str | None = None):
        """One vertically-stacked setting: bold label, control row, optional
        dim help text. Each block packs into the scrollable parent, so the
        whole tab flows naturally without grid-row arithmetic."""
        block = ttk.Frame(parent)
        block.pack(fill="x", padx=14, pady=(12, 0))
        ttk.Label(block, text=label, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ctrl = ttk.Frame(block)
        ctrl.pack(fill="x", pady=(4, 2))
        build_control(ctrl)
        if help_text:
            ttk.Label(
                block, text=help_text, foreground="#666",
                font=("Segoe UI", 9), wraplength=600, justify="left",
            ).pack(anchor="w", pady=(0, 4))

    def _slider_inline(self, parent, var: tk.IntVar, lo: int, hi: int):
        scale = ttk.Scale(parent, from_=lo, to=hi, variable=var,
                          command=lambda v: var.set(int(float(v))))
        scale.pack(side="left", fill="x", expand=True)
        ttk.Label(parent, textvariable=var, width=5, anchor="e"
                 ).pack(side="right", padx=(8, 0))

    # -- tab construction --------------------------------------------------

    def _build_tab(self, parent, screen: int) -> dict[str, tk.Variable]:
        s = self.config["screens"][str(screen)]
        vars_: dict[str, tk.Variable] = {}

        # Background image picker
        def _bg(p):
            bg_var = tk.StringVar(value=s["bgImage"])
            vars_["bgImage"] = bg_var
            ttk.Entry(p, textvariable=bg_var).pack(side="left", fill="x", expand=True)
            ttk.Button(p, text="Browse…",
                       command=lambda: self._pick_image(bg_var)).pack(side="right", padx=(8, 0))
        self._setting_block(
            parent, "Background image", _bg,
            "Image displayed behind the glow layer. Use a PNG with transparent "
            "regions where you want the SignalRGB colours to shine through — JPG "
            "and WebP also work for fully-opaque backgrounds. Tip: the "
            "Build Wallpaper… tray menu can carve transparency out of any image.",
        )

        # Image fit
        def _fit(p):
            fit_var = tk.StringVar(value=s["bgFit"] if s["bgFit"] in BG_FIT_CHOICES else "cover")
            vars_["bgFit"] = fit_var
            ttk.OptionMenu(p, fit_var, fit_var.get(), *BG_FIT_CHOICES
                          ).pack(side="left", fill="x", expand=True)
        self._setting_block(
            parent, "Image fit", _fit,
            "How the background image fills the screen. 'cover' preserves aspect "
            "ratio and crops the overflowing edges; 'contain' shows the whole "
            "image with letterboxing; 'fill' stretches it to exactly the screen "
            "dimensions (will distort).",
        )

        # Image dim
        def _dim(p):
            dim_var = tk.IntVar(value=int(s["bgDim"]))
            vars_["bgDim"] = dim_var
            self._slider_inline(p, dim_var, 0, 100)
        self._setting_block(
            parent, "Image dim (%)", _dim,
            "Darkens the background image. 0 = original brightness, 100 = fully "
            "black. Useful when the wallpaper is bright and competes with the "
            "glow — bumping dim to 30-50 makes the colours pop.",
        )

        # Glow layout
        def _layout(p):
            layout_var = tk.StringVar(value=s["barLayout"])
            vars_["barLayout"] = layout_var
            labels = [label for _key, label in LAYOUT_CHOICES]
            label_to_key = {label: key for key, label in LAYOUT_CHOICES}
            current_label = next(
                (label for key, label in LAYOUT_CHOICES if key == layout_var.get()),
                labels[0],
            )
            display_var = tk.StringVar(value=current_label)
            def _on_change(lbl: str):
                layout_var.set(label_to_key.get(lbl, "lay-grid"))
            ttk.OptionMenu(p, display_var, current_label, *labels, command=_on_change
                          ).pack(side="left", fill="x", expand=True)
        self._setting_block(
            parent, "Glow layout", _layout,
            "How the colours from SignalRGB are rendered. Pixel Grid (2D) maps "
            "the full N×N matrix, one cell per LED. Vertical/Horizontal Stripes "
            "show wide bands across the screen. Centered Pills looks like a "
            "sound visualiser. Hidden disables the glow (image-only).",
        )

        # Enable glow
        def _show(p):
            show_var = tk.BooleanVar(value=bool(s["showBars"]))
            vars_["showBars"] = show_var
            ttk.Checkbutton(p, text="Show the glow layer", variable=show_var
                           ).pack(side="left")
        self._setting_block(
            parent, "Enable glow", _show,
            "Master on/off. When off, only the background image is shown — useful "
            "for previewing the image alone before adding the glow back.",
        )

        # Glow strength
        def _gs(p):
            gs_var = tk.IntVar(value=int(s["glowStrength"]))
            vars_["glowStrength"] = gs_var
            self._slider_inline(p, gs_var, 0, 200)
        self._setting_block(
            parent, "Glow strength (%)", _gs,
            "Brightness multiplier on the glow layer. 100 = baseline, 200 = "
            "double-bright (good for dark wallpapers / dim ambient light), "
            "0 = invisible.",
        )

        # Grid blur
        def _gb(p):
            gb_var = tk.IntVar(value=int(s["gridBlur"]))
            vars_["gridBlur"] = gb_var
            self._slider_inline(p, gb_var, 0, 200)
        self._setting_block(
            parent, "Grid blur (px)", _gb,
            "Softens the seams between adjacent grid cells. 0 = sharp pixel "
            "grid (visible cells), 200 = creamy gradient across the screen. "
            "Pixel Grid layout only.",
        )

        # Stripes blur
        def _sb(p):
            sb_var = tk.IntVar(value=int(s["stripesBlur"]))
            vars_["stripesBlur"] = sb_var
            self._slider_inline(p, sb_var, 0, 200)
        self._setting_block(
            parent, "Stripes blur (px)", _sb,
            "Softens the edges between stripes. Vertical/Horizontal Stripes "
            "layouts only.",
        )

        # Bar height
        def _bh(p):
            bh_var = tk.IntVar(value=int(s["barHeight"]))
            vars_["barHeight"] = bh_var
            self._slider_inline(p, bh_var, 10, 100)
        self._setting_block(
            parent, "Bar height (% of screen)", _bh,
            "Pill height as a percent of screen height. Centered Pills layout only.",
        )

        # Bar width
        def _bw(p):
            bw_var = tk.IntVar(value=int(s["barWidth"]))
            vars_["barWidth"] = bw_var
            self._slider_inline(p, bw_var, 1, 50)
        self._setting_block(
            parent, "Bar width (‰ of screen)", _bw,
            "Pill width in per-mille (thousandths) of screen width. Centered "
            "Pills layout only — keep low for thin bars, raise for chunky ones.",
        )

        # Debug overlay
        def _dbg(p):
            ss_var = tk.BooleanVar(value=bool(s["showStatus"]))
            vars_["showStatus"] = ss_var
            ttk.Checkbutton(p, text="Show top-left status line", variable=ss_var
                           ).pack(side="left")
        self._setting_block(
            parent, "Show debug overlay", _dbg,
            "Tiny status line in the top-left of the wallpaper showing the "
            "bridge connection state and current frame rate. Useful for "
            "troubleshooting; leave off in normal use.",
        )

        # Bottom padding so the last block has breathing room when scrolled.
        ttk.Frame(parent, height=12).pack(fill="x")
        return vars_

    def _pick_image(self, var: tk.StringVar):
        path = filedialog.askopenfilename(
            title="Pick background image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp *.svg *.bmp"),
                       ("All files", "*.*")],
        )
        if path:
            var.set(path)

    # -- save / cancel ------------------------------------------------------

    def _on_save(self):
        # Collect every Var into the in-memory config (the dialog received a
        # deep-copy so we won't disturb the live config until the caller
        # accepts it).
        try:
            self.config["screenCount"] = max(1, min(N_SCREENS, int(self.global_vars["screenCount"].get())))
        except Exception:
            self.config["screenCount"] = 1
        try:
            self.config["fullscreenPause"] = bool(self.global_vars["fullscreenPause"].get())
        except Exception:
            self.config["fullscreenPause"] = True
        for n in range(N_SCREENS):
            settings = {k: var.get() for k, var in self.vars[n].items()}
            self.config["screens"][str(n)] = settings
        # Caller persists + pushes to live wallpapers. We deliberately keep
        # the dialog open so the user can iterate (test, switch tabs, tweak
        # the next screen) without re-opening it from the tray every time.
        self.on_save(self.config)
        if self._saved_label is not None:
            self._saved_label.config(text="✓ Saved at " + time.strftime("%H:%M:%S"))

    def _on_close(self):
        if self.root is not None:
            self.root.destroy()


# ============================================================================
# About dialog
# ============================================================================

class AboutDialog:
    """Standalone Tk window with version info, author block + avatar, and
    quick links. The full open-source attributions live in docs/credits.md
    on GitHub now — the dialog links to them instead of embedding the wall
    of text. Spawned per tray click, on its own daemon thread."""

    # Class-level cache so a second About-open during the same process
    # doesn't re-hit GitHub for the avatar.
    _avatar_pil_cached: "Image.Image | None" = None

    def _get_avatar(self) -> "Image.Image | None":
        if AboutDialog._avatar_pil_cached is not None:
            return AboutDialog._avatar_pil_cached
        try:
            req = urllib.request.Request(
                f"https://github.com/{APP_GITHUB_USER}.png?size=128",
                headers={"User-Agent": f"SignalRGBWallpaper-About/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = r.read()
            img = Image.open(BytesIO(data)).convert("RGBA")
            img.thumbnail((96, 96), Image.LANCZOS)
            AboutDialog._avatar_pil_cached = img
            return img
        except Exception as e:
            print(f"[about] avatar fetch failed: {e}")
            return None

    def show(self):
        root = tk.Tk()
        root.title(tr("about.title", app=APP_NAME))
        root.geometry("520x420")
        root.minsize(480, 380)

        # Title block
        ttk.Label(root, text=APP_NAME,
                  font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(18, 0))
        ttk.Label(root, text=tr("about.version", ver=APP_VERSION),
                  foreground="#666").pack(anchor="w", padx=18, pady=(0, 12))

        # Author card: avatar (left) + name + GitHub handle + copyright (right)
        author = ttk.Frame(root)
        author.pack(fill="x", padx=18, pady=(0, 6))

        avatar_img = self._get_avatar()
        if avatar_img is not None:
            try:
                photo = ImageTk.PhotoImage(avatar_img, master=root)
                avatar_lbl = ttk.Label(author, image=photo)
                avatar_lbl.image = photo   # keep a ref so Tk doesn't GC it
                avatar_lbl.pack(side="left", padx=(0, 14))
            except Exception as e:
                print(f"[about] tk image failed: {e}")

        text_col = ttk.Frame(author)
        text_col.pack(side="left", fill="x", expand=True)
        ttk.Label(text_col, text=APP_AUTHOR,
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        handle_text = tr("about.github_handle", user=APP_GITHUB_USER)
        handle_lbl = ttk.Label(text_col, text=handle_text,
                               foreground="#3a6ba8", cursor="hand2")
        handle_lbl.pack(anchor="w")
        handle_lbl.bind("<Button-1>", lambda _e: webbrowser.open(APP_AUTHOR_URL))
        ttk.Label(text_col,
                  text=tr("about.copyright", author=APP_AUTHOR),
                  foreground="#666").pack(anchor="w", pady=(8, 0))

        # One-line tagline
        ttk.Separator(root).pack(fill="x", padx=18, pady=(14, 12))
        ttk.Label(root, text=tr("about.tagline"),
                  wraplength=460, foreground="#444"
                  ).pack(anchor="w", padx=18, pady=(0, 14))

        # Quick links
        links = ttk.Frame(root)
        links.pack(fill="x", padx=18, pady=(0, 6))
        ttk.Button(links, text=tr("about.btn.github"),
                   command=lambda: webbrowser.open(APP_REPO)).pack(side="left")
        ttk.Button(links, text=tr("about.btn.license"),
                   command=lambda: webbrowser.open(APP_REPO + "/blob/main/LICENSE")
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(links, text=tr("about.btn.credits"),
                   command=lambda: webbrowser.open(APP_CREDITS_URL)
                   ).pack(side="left", padx=(6, 0))

        donate = ttk.Frame(root)
        donate.pack(fill="x", padx=18, pady=(2, 6))
        ttk.Button(donate, text=tr("about.btn.donate"),
                   command=lambda: webbrowser.open(APP_DONATE_URL)).pack(side="left")

        # Footer / close
        btn_row = ttk.Frame(root)
        btn_row.pack(fill="x", padx=18, pady=(16, 14), side="bottom")
        ttk.Button(btn_row, text=tr("about.btn.close"),
                   command=root.destroy).pack(side="right")

        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()


# ============================================================================
# System Status dialog
# ============================================================================

class SystemStatusDialog:
    """Tk dialog that shows green/red rows for each "is the install
    actually working?" signal and offers a one-click *Fix this…* button
    per red row. Spawned per tray click on a daemon thread."""

    def __init__(self, bridge: BridgeRuntime):
        self.bridge = bridge

    def show(self):
        status = self.bridge.get_health_status()
        root = tk.Tk()
        root.title(tr("status.title"))
        root.geometry("520x360")
        root.minsize(460, 320)

        ttk.Label(root, text=tr("status.title"),
                  font=("Segoe UI", 13, "bold")).pack(
                      anchor="w", padx=18, pady=(16, 0))
        ttk.Label(root, text=tr("status.subtitle"),
                  foreground="#666").pack(
                      anchor="w", padx=18, pady=(0, 12))

        rows = ttk.Frame(root)
        rows.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        # Build each status row. `(ok, label, fix_label, fix_action)`.
        # `fix_action` is None when there's nothing useful to do — the
        # row still renders a red dot but no button.
        def open_plugin_dir():
            try:
                Path(status["plugin_dir"]).mkdir(parents=True, exist_ok=True)
                os.startfile(status["plugin_dir"])
            except Exception as e:
                print(f"[status] open plugin dir failed: {e}")

        def open_signalrgb_dl():
            webbrowser.open("https://signalrgb.com/")

        def open_lhm_dl():
            webbrowser.open("https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases")

        def open_help_pages():
            try: webbrowser.open(f"http://{WS_HOST}:{WS_PORT}/help")
            except Exception: pass

        entries = [
            (status["plugin_present"],
             tr("status.plugin"),
             tr("status.btn.open_plugins"),
             open_plugin_dir),
            (status["signalrgb_running"],
             tr("status.signalrgb"),
             tr("status.btn.get_signalrgb"),
             open_signalrgb_dl),
            (True,
             tr("status.bridge", host=WS_HOST, port=WS_PORT),
             None, None),  # if this dialog renders, the bridge is up
            (status["pages_connected"] > 0,
             tr("status.pages", n=status["pages_connected"]),
             tr("status.btn.help"),
             open_help_pages),
        ]
        # LHM row only appears if a Hardware-sensor widget is in use —
        # otherwise its status is irrelevant.
        if status["lhm_widget_present"]:
            entries.append((
                status["lhm_online"],
                tr("status.lhm", n=status["lhm_count"]),
                tr("status.btn.get_lhm"),
                open_lhm_dl,
            ))

        for ok, label, fix_label, fix_action in entries:
            row = ttk.Frame(rows)
            row.pack(fill="x", pady=4)
            dot = tk.Label(row, text="●", font=("Segoe UI", 16),
                           fg=("#3aa86d" if ok else "#cc4a4a"))
            dot.pack(side="left", padx=(0, 10))
            ttk.Label(row, text=label,
                      wraplength=320, justify="left").pack(
                          side="left", fill="x", expand=True)
            if not ok and fix_action is not None and fix_label:
                ttk.Button(row, text=fix_label,
                           command=fix_action).pack(side="right")

        # Footer
        btn_row = ttk.Frame(root)
        btn_row.pack(fill="x", padx=18, pady=(8, 14), side="bottom")
        ttk.Button(btn_row, text=tr("status.btn.refresh"),
                   command=lambda: (root.destroy(),
                                    SystemStatusDialog(self.bridge).show())
                  ).pack(side="left")
        ttk.Button(btn_row, text=tr("about.btn.close"),
                   command=root.destroy).pack(side="right")

        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()


# ============================================================================
# Tray icon
# ============================================================================

def build_tray_image() -> Image.Image:
    """Generate a 64x64 tray icon: monitor with five RGB pads underneath."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Monitor body
    d.rounded_rectangle((6, 8, 58, 42), radius=3, outline=(74, 81, 96, 255), width=2, fill=(27, 31, 42, 255))
    d.rectangle((10, 12, 54, 38), fill=(5, 6, 8, 255))
    # Stand
    d.rectangle((26, 46, 38, 49), fill=(74, 81, 96, 255))
    d.rectangle((20, 50, 44, 52), fill=(74, 81, 96, 255))
    # Five RGB pads under the screen edge
    pad_colors = [(255, 45, 106), (255, 143, 45), (255, 233, 45), (66, 255, 133), (45, 180, 255)]
    centers = [17, 25, 33, 41, 49]
    for cx, color in zip(centers, pad_colors):
        d.ellipse((cx - 3, 25, cx + 3, 31), fill=color + (255,))
    return img


class TrayApp:
    def __init__(self, bridge: BridgeRuntime, config: dict, config_lock: threading.Lock):
        self.bridge = bridge
        self.config = config
        self.config_lock = config_lock
        self.icon: pystray.Icon | None = None
        # Background update checker — polls GitHub releases daily + on demand.
        # Callbacks refresh the tray menu so the "Update available" entry
        # and "last checked" timestamps stay live without a restart.
        self.update_checker = UpdateChecker(
            config, config_lock,
            on_update_available=self._on_update_available,
            on_check_done=self._on_update_check_done,
        )

    def run(self):
        # Top-level menu is dynamic so the "Update available…" entry can
        # appear / disappear based on the checker's state without
        # rebuilding the Icon.
        menu = pystray.Menu(self._build_top_menu)
        self.icon = pystray.Icon(
            name="SignalRGBWallpaper",
            icon=build_tray_image(),
            title="SignalRGB Wallpaper Bridge",
            menu=menu,
        )
        self.update_checker.start()
        self.icon.run()

    def _build_top_menu(self):
        items = []
        avail = self.update_checker.available()
        if avail:
            tag, _ = avail
            has_installer = self.update_checker.available_asset() is not None
            items.append(pystray.MenuItem(
                tr("updates.available_top", tag=tag),
                self._open_update_page))
            # Only offer the one-click install when the release ships
            # an installer asset (older betas didn't always).
            if has_installer:
                items.append(pystray.MenuItem(
                    tr("updates.install_now", tag=tag),
                    self._download_and_install_update))
            items.append(pystray.Menu.SEPARATOR)
        # Cheap snapshot of the lock state across active screens so the
        # Lock/Unlock entry can switch label without opening a submenu.
        any_unlocked = self._any_screen_unlocked()
        items.extend([
            pystray.MenuItem(tr("tray.configurator"), self._open_configurator, default=True),
            pystray.MenuItem(tr("tray.builder"),      self._open_builder),
            pystray.MenuItem(tr("tray.help"),         self._open_help),
            pystray.MenuItem(tr("tray.status"),       self._open_status),
            pystray.MenuItem(
                tr("tray.lock_all") if any_unlocked else tr("tray.unlock_all"),
                self._toggle_widgets_lock_all),
            # v1.2.3: manual Pause / Resume. Independent of the
            # fullscreen-watcher auto-pause; freezes glow + animations
            # on every screen on demand (e.g. to save GPU while AFK
            # without launching a fullscreen app). Checkmark reflects
            # the current manual state.
            pystray.MenuItem(
                tr("tray.pause"),
                self._toggle_manual_pause,
                checked=lambda _i: self.bridge.is_manual_paused()),
            pystray.Menu.SEPARATOR,
            # v1.2.1: most of the old "Advanced" submenu moved into the
            # Configurator's new System section. What stays here are the
            # screen-scoped quick-mutation menus (Add widget / Quick
            # effects per screen) — those are deliberately per-screen and
            # don't fit the Configurator's "you're editing one screen at a
            # time" model. Toggles + maintenance buttons live in the
            # Configurator now to keep one source of truth.
            pystray.MenuItem(tr("tray.advanced"), pystray.Menu(
                pystray.MenuItem(tr("tray.quick_add_widget"), pystray.Menu(self._widget_menu_items)),
                pystray.MenuItem(tr("tray.quick_effects"),    pystray.Menu(self._effects_menu_items)),
                # v2.2.0-beta: shortcut into %LOCALAPPDATA%\…\library\
                # — the path the manual pack-extract instructions tell
                # users to drop ZIP contents into.
                pystray.MenuItem(tr("tray.open_library_folder"), self._open_library_folder),
                pystray.MenuItem(tr("tray.export_diagnostics"), self._export_diagnostics),
            )),
            pystray.MenuItem(tr("tray.updates"), pystray.Menu(self._update_menu_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(tr("tray.about"), self._open_about),
            pystray.MenuItem(tr("tray.quit"),  self._quit),
        ])
        return items

    def _open_configurator(self, icon, item):
        url = f"http://{WS_HOST}:{WS_PORT}/configurator"
        try: webbrowser.open(url, new=2)
        except Exception as e: print(f"[tray] open configurator failed: {e}")

    def _open_library_folder(self, icon, item):
        # v2.2.0-beta: opens %LOCALAPPDATA%\…\library\ in Explorer.
        # Same as POST /library/openfolder but tray-driven.
        try:
            lib = library_dir()
            lib.mkdir(parents=True, exist_ok=True)
            os.startfile(str(lib))   # type: ignore[attr-defined]
        except Exception as e:
            print(f"[tray] open library folder failed: {e}")

    # ── Top-level Lock / Unlock toggle ─────────────────────────────────
    # Picks the dominant state across all active screens — if any screen
    # is currently unlocked, the toggle locks them all; otherwise unlocks
    # them all. Keeps the per-screen Configurator + tray-Advanced flow
    # intact for users who need fine-grained control.

    def _any_screen_unlocked(self) -> bool:
        with self.config_lock:
            n = max(1, min(N_SCREENS, int(self.config.get("screenCount", 1))))
            for i in range(n):
                s = self.config["screens"].get(str(i), {})
                if s.get("widgetsLocked") is False:
                    return True
        return False

    def _toggle_manual_pause(self, icon, item):
        new_state = not self.bridge.is_manual_paused()
        self.bridge.set_manual_pause(new_state)
        try: icon.update_menu()
        except Exception: pass
        print(f"[tray] manual pause -> {new_state}")

    def _toggle_widgets_lock_all(self, icon, item):
        target_locked = self._any_screen_unlocked()    # if any unlocked → lock everything
        with self.config_lock:
            n = max(1, min(N_SCREENS, int(self.config.get("screenCount", 1))))
        for i in range(n):
            self.bridge.set_widgets_locked(i, target_locked)
        print(f"[tray] all screens widgetsLocked → {target_locked}")

    def _preset_hotkeys_enabled(self) -> bool:
        with self.config_lock:
            return bool(self.config.get("presetHotkeysEnabled", False))

    def _toggle_preset_hotkeys(self, icon, item):
        new_value = not self._preset_hotkeys_enabled()
        self.bridge.update_bridge_setting("presetHotkeysEnabled", new_value)
        # pystray queries `checked` lazily; redraw the menu so the
        # checkmark reflects the new state without a Windows mouse-out.
        try: icon.update_menu()
        except Exception: pass

    # -- menu callbacks (fire on pystray's worker thread) -------------------

    def _open_settings(self, icon, item):
        threading.Thread(target=self._show_settings_dialog, daemon=True,
                         name="settings-dialog").start()

    def _show_settings_dialog(self):
        # Snapshot under lock so the dialog gets a stable view; the dialog's
        # save callback will re-acquire the lock when mutating.
        with self.config_lock:
            cfg_view = json.loads(json.dumps(self.config))  # deep copy

        def on_save(updated_config: dict):
            # Replace the live config wholesale (covers screenCount + all
            # per-screen settings), persist to disk, and push every screen's
            # settings to any connected wallpaper pages.
            with self.config_lock:
                self.config.clear()
                self.config.update(updated_config)
                cfg_snapshot = json.loads(json.dumps(updated_config))
            try:
                save_config(cfg_snapshot)
            except Exception as e:
                print(f"[tray] save_config failed: {e}")
            for n in range(N_SCREENS):
                self.bridge.push_settings(n, cfg_snapshot["screens"][str(n)])

        dialog = SettingsDialog(cfg_view, on_save)
        try:
            dialog.show()
        except Exception as e:
            print(f"[tray] settings dialog crashed: {e}")

    def _open_about(self, icon, item):
        threading.Thread(target=self._show_about_dialog, daemon=True,
                         name="about-dialog").start()

    def _show_about_dialog(self):
        try:
            AboutDialog().show()
        except Exception as e:
            print(f"[tray] about dialog crashed: {e}")

    def _open_status(self, icon, item):
        threading.Thread(target=self._show_status_dialog, daemon=True,
                         name="status-dialog").start()

    def _show_status_dialog(self):
        try:
            SystemStatusDialog(self.bridge).show()
        except Exception as e:
            print(f"[tray] status dialog crashed: {e}")

    def _open_builder(self, icon, item):
        # Open the bundled HTML wallpaper builder in the user's default
        # browser. The bridge serves it at /builder on the same port the
        # WS / image proxy listen on, so the URL is always reachable when
        # the bridge is running.
        url = f"http://{WS_HOST}:{WS_PORT}/builder"
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            print(f"[tray] failed to open browser: {e}")

    def _resolve_desktop_path(self) -> Path:
        """Find the user's real Desktop folder. On OneDrive-synced
        accounts the in-explorer "Desktop" is actually at
        `%USERPROFILE%\\OneDrive\\Desktop`, not `%USERPROFILE%\\Desktop`,
        so a naive `Path.home() / "Desktop"` writes into the wrong
        place (or a shadow folder the user never opens). Check the
        Windows known-folder registry value first; fall back to the
        OneDrive candidate, then to the legacy home/Desktop, then to
        home itself."""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
                val, _ = winreg.QueryValueEx(k, "Desktop")
                p = Path(os.path.expandvars(val))
                if p.exists():
                    return p
        except Exception:
            pass
        for candidate in (
            Path.home() / "OneDrive" / "Desktop",
            Path.home() / "Desktop",
            Path.home(),
        ):
            if candidate.exists():
                return candidate
        return Path.home()

    def _export_diagnostics(self, icon, item):
        """v1.2.14: bundle the bridge config + last-known errors +
        screen / library / install paths into a single ZIP on the
        user's Desktop so bug reports stop needing five round-trips
        of 'paste your config' / 'paste the log' / etc. Secrets-redacted:
        the only field we knowingly carry that could leak anything is
        bgImage absolute paths — those stay because they're useful for
        diagnosing path issues.

        v1.2.15: harden the Desktop resolution for OneDrive-synced
        setups + open Explorer with the ZIP pre-selected so the user
        immediately sees where it landed (the tray balloon alone was
        easy to miss)."""
        import zipfile, subprocess, traceback
        try:
            desktop = self._resolve_desktop_path()
            stamp = time.strftime("%Y%m%d-%H%M%S")
            out = desktop / f"signalrgb-wallpaper-diagnostics-{stamp}.zip"
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                # config.json (redacted copy)
                try:
                    with self.config_lock:
                        cfg = json.loads(json.dumps(self.config))
                    zf.writestr("config.json", json.dumps(cfg, indent=2, ensure_ascii=False))
                except Exception as e:
                    zf.writestr("config.json.error", f"snapshot failed: {e}")
                # Version + platform + paths summary
                summary = {
                    "app_version":    APP_VERSION,
                    "python_version": sys.version,
                    "platform":       sys.platform,
                    "config_path":    str(config_path()),
                    "screens_dir":    str(screens_dir()),
                    "library_dir":    str(library_dir()),
                    "frozen":         bool(getattr(sys, "frozen", False)),
                    "executable":     str(getattr(sys, "executable", "")),
                    "exported_at":    stamp,
                }
                zf.writestr("summary.json", json.dumps(summary, indent=2))
                # library.json — useful for catalogue + cycle debugging
                try:
                    cat = library_dir() / "library.json"
                    if cat.exists():
                        zf.writestr("library.json", cat.read_text(encoding="utf-8"))
                except Exception as e:
                    zf.writestr("library.json.error", str(e))
                # Re-import log (last run)
                try:
                    reimport_log = Path(os.environ.get("TEMP",
                        str(Path.home() / "AppData" / "Local" / "Temp"))) / "signalrgb-reimport.log"
                    if reimport_log.exists():
                        zf.writestr("reimport.log", reimport_log.read_text(encoding="utf-8", errors="replace"))
                except Exception as e:
                    zf.writestr("reimport.log.error", str(e))
                # v1.2.13: persistent bridge log + its rotated siblings.
                try:
                    log_dir = Path(os.environ.get("LOCALAPPDATA",
                        str(Path.home() / "AppData" / "Local"))) \
                        / "SignalRGBWallpaper" / "logs"
                    for entry in sorted(log_dir.glob("bridge.log*")):
                        try:
                            zf.writestr(f"logs/{entry.name}",
                                        entry.read_text(encoding="utf-8",
                                                        errors="replace"))
                        except Exception as e:
                            zf.writestr(f"logs/{entry.name}.error", str(e))
                except Exception as e:
                    zf.writestr("logs.error", str(e))
            print(f"[diagnostics] exported {out}")
            # Pop Explorer with the file pre-selected so the user can't
            # miss where the bundle landed.
            try:
                CREATE_NO_WINDOW = 0x08000000
                subprocess.Popen(["explorer.exe", "/select,", str(out)],
                                 creationflags=CREATE_NO_WINDOW)
            except Exception as e:
                print(f"[diagnostics] explorer popup failed: {e}")
            self._tray_notify(tr("diagnostics.done", path=str(out)),
                              tr("tray.export_diagnostics"))
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[diagnostics] export failed: {e}\n{tb}")
            self._tray_notify(tr("diagnostics.failed", msg=str(e)),
                              tr("tray.export_diagnostics"))

    def _open_help(self, icon, item):
        # Help page — scenario walkthroughs (1/2/3/4 monitors × Lively /
        # Wallpaper Engine) plus a Tips section. Same browser-served
        # pattern as Configurator / Builder.
        url = f"http://{WS_HOST}:{WS_PORT}/help"
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            print(f"[tray] failed to open browser: {e}")

    # ── Updates submenu ────────────────────────────────────────────────
    # Manual trigger + the two toggles + a status line ("up-to-date /
    # last error / pending"). Rebuilt on every open so the status reflects
    # the latest poll without any push from the checker side.

    def _update_menu_items(self):
        with self.config_lock:
            enabled = bool(self.config.get("updateCheckEnabled", True))
            beta    = bool(self.config.get("allowBetas", False))
        avail   = self.update_checker.available()
        last_t  = self.update_checker.last_checked()
        err     = self.update_checker.last_error()
        items = [
            pystray.MenuItem(tr("updates.check_now"),  self._check_updates_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(tr("updates.enable"),     self._toggle_update_enabled,
                             checked=lambda _it, _e=enabled: _e),
            pystray.MenuItem(tr("updates.allow_beta"), self._toggle_allow_betas,
                             checked=lambda _it, _b=beta: _b),
            pystray.Menu.SEPARATOR,
        ]
        if avail:
            tag, _ = avail
            items.append(pystray.MenuItem(
                tr("updates.latest", tag=tag),
                self._open_update_page))
        elif err:
            short = (err[:48] + "…") if len(err) > 48 else err
            items.append(pystray.MenuItem(tr("updates.last_failed", err=short),
                                          None, enabled=False))
        elif last_t > 0:
            ago = max(0, int(time.time() - last_t))
            if   ago < 60:   ago_s = tr("ago.s", n=ago)
            elif ago < 3600: ago_s = tr("ago.m", n=ago // 60)
            else:            ago_s = tr("ago.h", n=ago // 3600)
            items.append(pystray.MenuItem(tr("updates.up_to_date", ago=ago_s),
                                          None, enabled=False))
        else:
            items.append(pystray.MenuItem(tr("updates.not_checked"),
                                          None, enabled=False))
        items.append(pystray.MenuItem(tr("updates.installed", ver=APP_VERSION),
                                      None, enabled=False))
        return items

    def _check_updates_now(self, icon, item):
        self.update_checker.check_now()

    def _open_update_page(self, icon, item):
        avail = self.update_checker.available()
        url = avail[1] if avail else UPDATE_RELEASES_HTML
        try: webbrowser.open(url, new=2)
        except Exception as e: print(f"[tray] open release page failed: {e}")

    def _open_library_folder(self, icon, item):
        """v1.2.13: pop an Explorer window at the library folder so
        the user can drop several backgrounds in / clean up old ones
        without going through the Configurator's `Choose image…`
        picker one at a time. Triggered from the new Configurator
        button via a `system-action`.

        v1.2.13.1: switched the spawn from
        `subprocess.Popen(["explorer.exe", path], CREATE_NO_WINDOW)`
        to `os.startfile(path)` — the Popen path silently no-op'd for
        at least one user, likely because explorer.exe with
        CREATE_NO_WINDOW + no parent console on some Windows
        configurations exits immediately. `os.startfile` is the
        canonical "open this in the default shell handler" call and
        always lands Explorer for a directory path."""
        try:
            lib = library_dir()
            lib.mkdir(parents=True, exist_ok=True)
            try:
                os.startfile(str(lib))   # type: ignore[attr-defined]
            except AttributeError:
                # Non-Windows fallback — covers dev runs on Linux/macOS.
                subprocess.Popen(["xdg-open", str(lib)])
        except Exception as e:
            print(f"[tray] open library folder failed: {e}")

    def _download_and_install_update(self, icon, item):
        """Tray entry: download the pending update's installer to %TEMP%
        and launch it silently. The bridge exits once the installer is
        running so it can replace SignalRGBBridge.exe in place; the
        installer's [Run] section re-launches the new bridge."""
        avail = self.update_checker.available()
        if not avail:
            return
        tag = avail[0]
        # Use a tiny Tk window for progress so the user knows the
        # download is happening (the installer asset is ~20 MB so a
        # cold-cache download can take a few seconds). Falls back to a
        # console-only path if Tk isn't available for some reason.
        def show_progress_window():
            root = tk.Tk()
            root.title(tr("updates.installing_title", tag=tag))
            root.geometry("440x140")
            root.resizable(False, False)
            label_var = tk.StringVar(value=tr("updates.installing_start"))
            ttk.Label(root, textvariable=label_var,
                      wraplength=400, justify="left").pack(
                          anchor="w", padx=18, pady=(18, 6))
            pb = ttk.Progressbar(root, mode="determinate", length=400, maximum=100)
            pb.pack(padx=18, pady=6)
            ttk.Label(root, text=tr("updates.installing_hint"),
                      foreground="#888",
                      wraplength=400).pack(anchor="w", padx=18, pady=(0, 10))
            def on_progress(done, total):
                pct = (done * 100 / total) if total > 0 else 0
                root.after(0, lambda: (
                    pb.configure(value=pct),
                    label_var.set(tr("updates.installing_progress",
                                     pct=int(pct),
                                     done_mb=done // (1024*1024),
                                     total_mb=(total // (1024*1024)) if total else 0))
                ))
            def on_done(path, err):
                root.after(0, lambda: (
                    label_var.set(tr("updates.installing_done") if path
                                  else tr("updates.installing_failed", msg=err or "")),
                ))
                # Don't auto-close — the os._exit kills this window too
                # when the bridge dies.
            self.update_checker.download_and_install(on_progress, on_done)
            root.mainloop()
        threading.Thread(target=show_progress_window, daemon=True,
                         name="update-progress").start()

    def _toggle_update_enabled(self, icon, item):
        with self.config_lock:
            cur = bool(self.config.get("updateCheckEnabled", True))
            self.config["updateCheckEnabled"] = not cur
            snap = json.loads(json.dumps(self.config))
        try: save_config(snap)
        except Exception as e: print(f"[tray] save_config failed: {e}")
        if not cur:    # we just enabled it → check now
            self.update_checker.check_now()

    def _toggle_allow_betas(self, icon, item):
        with self.config_lock:
            cur = bool(self.config.get("allowBetas", False))
            self.config["allowBetas"] = not cur
            snap = json.loads(json.dumps(self.config))
        try: save_config(snap)
        except Exception as e: print(f"[tray] save_config failed: {e}")
        # Re-check immediately so the user sees the effect of flipping
        # the prerelease filter without waiting a day.
        self.update_checker.check_now()

    def _on_update_available(self, tag: str, url: str):
        # Balloon notification — fires once per detected version bump.
        try:
            if self.icon:
                self.icon.notify(
                    tr("updates.balloon_msg", tag=tag),
                    tr("updates.balloon_title"),
                )
        except Exception as e:
            print(f"[tray] notify failed: {e}")
        # Force a menu rebuild so the "Update available" entry appears.
        try:
            if self.icon: self.icon.update_menu()
        except Exception: pass

    def _on_update_check_done(self, found: bool, error: str | None):
        # Refresh menu so the "last checked …s ago" status updates.
        try:
            if self.icon: self.icon.update_menu()
        except Exception: pass

    # ── Effects submenu ────────────────────────────────────────────────
    # Per-screen ambient preset / pixelfx mode / tint toggle. Live-pushed
    # to the wallpaper via the existing settings-broadcast pipeline.

    # i18n keys instead of raw labels — the actual text comes from tr() at
    # menu-build time, so a language change after first render reflects on
    # the next open.
    AMBIENT_PRESETS_TRAY = [
        ("off",    "ambient.off"),
        ("snow",   "ambient.snow"),
        ("rain",   "ambient.rain"),
        ("sparks", "ambient.sparks"),
        ("aurora", "ambient.aurora"),
    ]
    PIXELFX_MODES_TRAY = [
        ("off",    "pixelfx.off"),
        ("trail",  "pixelfx.trail"),
        ("glow",   "pixelfx.glow"),
        ("ripple", "pixelfx.ripple"),
        ("water",  "pixelfx.water"),
    ]

    def _effects_menu_items(self):
        with self.config_lock:
            n = max(1, min(N_SCREENS, int(self.config.get("screenCount", 1))))
        return [
            pystray.MenuItem(tr("tray.screen_n", n=i + 1),
                             pystray.Menu(self._effects_screen_items_factory(i)))
            for i in range(n)
        ]

    def _effects_screen_items_factory(self, screen: int):
        def items():
            with self.config_lock:
                s = self.config["screens"].get(str(screen), {})
                current_ambient = s.get("ambientEffect", "off")
                tint            = bool(s.get("ambientTint", False))
                current_pixelfx = s.get("pixelfx", "off")
            menu = []
            # Ambient preset radio list
            menu.append(pystray.MenuItem(tr("effects.ambient_label"),
                                         None, enabled=False))
            for value, key in self.AMBIENT_PRESETS_TRAY:
                menu.append(pystray.MenuItem(
                    "  " + tr(key),
                    self._set_ambient_factory(screen, value),
                    checked=lambda _it, _v=value, _c=current_ambient: _v == _c,
                    radio=True,
                ))
            menu.append(pystray.Menu.SEPARATOR)
            menu.append(pystray.MenuItem(
                tr("effects.tint_with_glow"),
                self._toggle_ambient_tint_factory(screen),
                checked=lambda _it, _t=tint: _t,
            ))
            menu.append(pystray.Menu.SEPARATOR)
            menu.append(pystray.MenuItem(tr("effects.pixelfx_label"),
                                         None, enabled=False))
            for value, key in self.PIXELFX_MODES_TRAY:
                menu.append(pystray.MenuItem(
                    "  " + tr(key),
                    self._set_pixelfx_factory(screen, value),
                    checked=lambda _it, _v=value, _c=current_pixelfx: _v == _c,
                    radio=True,
                ))
            return menu
        return items

    def _set_ambient_factory(self, screen: int, value: str):
        def handler(icon, item):
            with self.config_lock:
                s = self.config["screens"].setdefault(str(screen), {})
                s["ambientEffect"] = value
                snap = json.loads(json.dumps(s))
                full_snap = json.loads(json.dumps(self.config))
            try: save_config(full_snap)
            except Exception as e: print(f"[tray] save_config failed: {e}")
            self.bridge.push_settings(screen, snap)
            print(f"[tray] screen={screen} ambientEffect → {value}")
        return handler

    def _set_pixelfx_factory(self, screen: int, value: str):
        def handler(icon, item):
            with self.config_lock:
                s = self.config["screens"].setdefault(str(screen), {})
                s["pixelfx"] = value
                snap = json.loads(json.dumps(s))
                full_snap = json.loads(json.dumps(self.config))
            try: save_config(full_snap)
            except Exception as e: print(f"[tray] save_config failed: {e}")
            self.bridge.push_settings(screen, snap)
            print(f"[tray] screen={screen} pixelfx → {value}")
        return handler

    def _toggle_ambient_tint_factory(self, screen: int):
        def handler(icon, item):
            with self.config_lock:
                s = self.config["screens"].setdefault(str(screen), {})
                s["ambientTint"] = not bool(s.get("ambientTint", False))
                snap = json.loads(json.dumps(s))
                full_snap = json.loads(json.dumps(self.config))
            try: save_config(full_snap)
            except Exception as e: print(f"[tray] save_config failed: {e}")
            self.bridge.push_settings(screen, snap)
            print(f"[tray] screen={screen} ambientTint → {s['ambientTint']}")
        return handler

    # ── Widgets submenu ────────────────────────────────────────────────
    # Two layers of dynamic menus: outer = one entry per active screen
    # (driven by current screenCount), inner = Edit-toggle + per-type
    # Add items. Both rebuild on every menu open so screenCount changes
    # land without restarting the tray.

    def _widget_menu_items(self):
        with self.config_lock:
            n = max(1, min(N_SCREENS, int(self.config.get("screenCount", 1))))
        items = []
        for i in range(n):
            items.append(pystray.MenuItem(
                tr("tray.screen_n", n=i + 1),
                pystray.Menu(self._widget_screen_items_factory(i)),
            ))
        return items

    def _widget_screen_items_factory(self, screen: int):
        def items():
            with self.config_lock:
                s = self.config["screens"].get(str(screen), {})
                locked = bool(s.get("widgetsLocked", True))
                count  = len(s.get("widgets", []))
            state = tr("widgets.state.locked") if locked else tr("widgets.state.edit")
            menu = [
                pystray.MenuItem(
                    tr("widgets.edit_toggle", state=state),
                    self._toggle_widgets_lock_factory(screen),
                    checked=lambda _it, _locked=locked: not _locked,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(tr("widgets.placed_count", n=count),
                                 None, enabled=False),
                pystray.Menu.SEPARATOR,
            ]
            # Generate one "Add <Label>" entry per registered widget type.
            # Widget labels stay in English for now — they're proper nouns
            # ("Clock", "Calendar", …) and changing them per locale would
            # diverge from the labels shown in the in-browser picker.
            for wtype, cfg in WIDGET_DEFAULTS.items():
                label = cfg.get("label", wtype.title())
                menu.append(pystray.MenuItem(tr("widgets.add_x", label=label),
                                             self._add_widget_factory(screen, wtype)))
            return menu
        return items

    def _toggle_widgets_lock_factory(self, screen: int):
        def handler(icon, item):
            with self.config_lock:
                s = self.config["screens"].get(str(screen), {})
                new_locked = not bool(s.get("widgetsLocked", True))
            self.bridge.set_widgets_locked(screen, new_locked)
            print(f"[tray] screen={screen} widgetsLocked → {new_locked}")
        return handler

    def _add_widget_factory(self, screen: int, widget_type: str):
        def handler(icon, item):
            self.bridge.add_widget(screen, widget_type)
            print(f"[tray] screen={screen} added widget: {widget_type}")
        return handler

    def _reload_config(self, icon, item):
        try:
            reloaded = load_config()
            with self.config_lock:
                self.config.clear()
                self.config.update(reloaded)
            # Push to every screen so live wallpapers refresh
            for n in range(N_SCREENS):
                self.bridge.push_settings(n, reloaded["screens"][str(n)])
            print("[tray] config reloaded from disk")
        except Exception as e:
            print(f"[tray] reload failed: {e}")

    def _reload_wallpapers(self, icon, item):
        """Push a `reload` WS frame to every connected wallpaper page.
        Skips configurator clients (won't yank an open settings tab).
        Hot-reload path so a v0.X.Y → v0.X.Y+1 update with new
        wallpaper-page code lands without manually re-importing the
        Lively / WE bundle. Caveat: only works once the *previous*
        version is at least v0.9.13-beta (older versions don't have
        the reload listener yet) — Lively's cached extract still has
        to be refreshed manually that one time."""
        try:
            self.bridge.broadcaster.push_reload_all_threadsafe()
        except Exception as e:
            print(f"[tray] reload-wallpapers failed: {e}")

    def _reimport_bundles(self, icon, item):
        """Invoke the installer-side PowerShell helper that re-imports
        the SignalRGB Glow ZIPs into Lively (via its CLI) and bumps
        the WE project's `version` field so WE invalidates its cache
        on next apply.

        This is the user-facing fix for the long-standing pain point
        that the tray auto-update *only* updates the bridge — Lively
        and WE both cache the wallpaper-page bundle and don't pick
        up new JS / HTML until the user manually re-imports. The
        helper script automates that re-import end-to-end.

        Log lands at %TEMP%\\signalrgb-reimport.log for post-mortem."""
        import subprocess
        # The PowerShell script lives next to bridge.py in dev / next
        # to the exe in PyInstaller builds. Search both candidates.
        script_candidates = [
            Path(__file__).resolve().parent.parent / "installer" / "reimport-wallpaper-bundles.ps1",
            Path(getattr(sys, "_MEIPASS", "")) / "installer" / "reimport-wallpaper-bundles.ps1",
            Path(getattr(sys, "executable", "")).parent / "reimport-wallpaper-bundles.ps1",
        ]
        script = next((p for p in script_candidates if p and p.exists()), None)
        if not script:
            print("[tray] reimport-bundles: helper script not found in any expected location")
            self._toast_unavailable("re-import helper script missing")
            return
        log_path = Path(os.environ.get("TEMP", str(Path.home() / "AppData" / "Local" / "Temp"))) / "signalrgb-reimport.log"
        app_dir = Path(getattr(sys, "executable", "")).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        try:
            # `pwsh` (PowerShell 7) preferred, fall back to `powershell`
            # (Windows-shipped PS 5.1) so the helper works regardless of
            # whether the user installed the newer pwsh.
            #
            # CREATE_NO_WINDOW = 0x08000000 — suppresses the PowerShell
            # console flash users were seeing post-update. The script's
            # stdout is captured into the log file anyway; no reason to
            # show a console for the seconds it runs.
            CREATE_NO_WINDOW = 0x08000000
            ps_exe = "pwsh"
            try:
                subprocess.run([ps_exe, "-Version"], check=True,
                               capture_output=True, timeout=5,
                               creationflags=CREATE_NO_WINDOW)
            except Exception:
                ps_exe = "powershell"
            args = [
                ps_exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-WindowStyle", "Hidden",
                "-File", str(script),
                "-AppDir", str(app_dir),
            ]
            print(f"[tray] reimport-bundles: invoking {' '.join(args)}")
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=60,
                creationflags=CREATE_NO_WINDOW)
            try:
                with open(log_path, "w", encoding="utf-8") as fh:
                    fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] reimport invoked\n")
                    fh.write(f"  script: {script}\n")
                    fh.write(f"  app_dir: {app_dir}\n")
                    fh.write(f"  exit: {result.returncode}\n")
                    fh.write("─ stdout ─\n")
                    fh.write(result.stdout or "(empty)\n")
                    fh.write("─ stderr ─\n")
                    fh.write(result.stderr or "(empty)\n")
            except Exception:
                pass
            # Toast user via the tray icon's notify API — the WS
            # broadcast is only useful when wallpaper pages are
            # connected, and they likely aren't right after an
            # update.
            if result.returncode == 0:
                self._tray_notify(tr("tray.reimport_bundles.toast.ok"), tr("tray.reimport_bundles"))
            elif result.returncode == 4:
                # v2.4.3: nothing failed — the user's only WE copy is a
                # Steam Workshop subscription, which we can't update.
                self._tray_notify(tr("tray.reimport_bundles.toast.workshop"),
                                  tr("tray.reimport_bundles"))
            elif result.returncode in (2, 3):
                self._tray_notify(tr("tray.reimport_bundles.toast.partial"), tr("tray.reimport_bundles"))
            else:
                self._tray_notify(tr("tray.reimport_bundles.toast.fail"), tr("tray.reimport_bundles"))
        except Exception as e:
            print(f"[tray] reimport-bundles failed: {e}")
            self._tray_notify(tr("tray.reimport_bundles.toast.fail"), tr("tray.reimport_bundles"))

    def _tray_notify(self, message: str, title: str = "") -> None:
        """Best-effort tray balloon — falls back to console print
        if the icon isn't ready yet (some Windows / pystray
        combinations swallow the call silently before the first
        WM_TASKBARCREATED message)."""
        try:
            if getattr(self, "icon", None):
                self.icon.notify(message, title or "SignalRGB Wallpaper")
                return
        except Exception:
            pass
        print(f"[tray] notify (fallback): {title}: {message}")

    def _toast_unavailable(self, reason: str) -> None:
        self._tray_notify(
            tr("tray.reimport_bundles.toast.fail") + f"\n({reason})",
            tr("tray.reimport_bundles"))

    def _quit(self, icon, item):
        # Hard-kill the process immediately.
        # Why not icon.stop() + graceful return: in --noconsole PyInstaller
        # builds stdout is closed (print would raise OSError, swallowed by
        # pystray) and icon.stop() called from a callback thread sometimes
        # blocks on the message-pump drain — we'd hang with the tray icon
        # gone but the process still alive (exactly the bug the user hit).
        # We have nothing worth flushing here: config is persisted on every
        # Save, no in-flight writes. os._exit bypasses atexit and threads
        # cleanly.
        os._exit(0)


# ============================================================================
# Main
# ============================================================================

def main():
    config = load_config()
    init_language(config)
    config_lock = threading.Lock()

    # Rebuild the library catalogue from the directory contents on every
    # startup. The installer copies its bundled `library.json` over the
    # user's, which lists only the starter wallpapers — without this
    # step, user-uploaded PNGs (still on disk) wouldn't appear in the
    # Configurator strip until the next upload/delete forces a rebuild.
    # `_library_rebuild_catalogue` preserves pin/order/addedAt for any
    # entries that survived the overwrite, so this is safe to run
    # unconditionally.
    try:
        _library_rebuild_catalogue(library_dir())
    except Exception as e:
        print(f"[library] startup rebuild failed: {e}")

    bridge = BridgeRuntime(config, config_lock)
    bridge.start()

    if not _HAS_TRAY:
        # No GUI stack — tkinter, pystray or ImageTk failed to import.
        # On Windows that should never happen and is worth saying loudly;
        # on Linux it is the expected state until the tray gets a native
        # equivalent, and the browser Configurator is the primary UI
        # there anyway.
        #
        # bridge.tray must not be left as None: the Configurator's
        # `system-action` WS commands call through it, and None would
        # turn a harmless "reload config" click into an AttributeError
        # deep in a handler. A stub that ignores unknown attributes
        # keeps those paths inert instead of fatal.
        print(f"[tray] unavailable ({_TRAY_IMPORT_ERROR}) — running headless")
        print(f"[tray] Configurator: http://{WS_HOST}:{WS_PORT}/configurator")

        class _NoTray:
            """Absorbs every tray call as a no-op. See above."""
            def __getattr__(self, name):
                def _noop(*a, **kw):
                    print(f"[tray] {name}() ignored — no tray on this platform")
                    return None
                return _noop

        bridge.tray = _NoTray()
        try:
            threading.Event().wait()      # park the main thread
        except KeyboardInterrupt:
            print("[tray] interrupted — shutting down")
        return

    tray = TrayApp(bridge, config, config_lock)
    # v1.2.1: hand the tray reference back to the bridge so the
    # Configurator's System-section `system-action` WS commands
    # can invoke the same maintenance handlers the tray's Advanced
    # submenu used to call (reload-config / reload-wallpapers /
    # reimport-bundles / check-updates-now / open-releases).
    bridge.tray = tray

    # ── Auto-chain marker check (v1.1.5+) ──
    # If the tray's "Download + install update" path queued a
    # post-update re-import, do it now. Wrapping in a 5 s delay
    # so the tray icon is up + the wallpaper pages have time to
    # reconnect before we shell out to PowerShell — the user gets
    # to see "I'm running" before the script's progress dialog
    # appears.
    try:
        cfg_dir = Path(os.environ.get("LOCALAPPDATA",
            str(Path.home() / "AppData" / "Local"))) / "SignalRGBWallpaper"
        marker = cfg_dir / ".pending-reimport"
        if marker.exists():
            print(f"[startup] re-import marker found at {marker} — scheduling auto-chain")
            def _run_pending_reimport():
                time.sleep(5)
                try:
                    tray._reimport_bundles(None, None)
                except Exception as e:
                    print(f"[startup] auto-chain reimport failed: {e}")
                try:
                    marker.unlink()
                except Exception:
                    pass
            threading.Thread(target=_run_pending_reimport,
                             daemon=True, name="auto-chain-reimport").start()
    except Exception as e:
        print(f"[startup] marker check failed (non-fatal): {e}")

    tray.run()  # blocks on Win32 message pump


if __name__ == "__main__":
    main()
