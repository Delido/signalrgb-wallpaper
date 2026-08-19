"""Reset all screen settings — scope, safety net, and reachability.

WHY THIS EXISTS

reset_screen() has existed for a while, but only ever applied to one
screen and was reached from that screen's own card. Recovering a
thoroughly mangled multi-screen setup meant repeating it per screen, and
there was no single "put it back how it was". Requested as: "es fehlt
noch ein Button wie Reset all Settings".

The dangerous part of a reset button is not the reset — it is the scope
creep. This one deliberately touches only per-screen appearance:

  * kept: preset slots, per-app profiles, the image library, and every
    bridge-level option (language, update checks, OpenRGB/sACN/MQTT).
    Those are laborious to recreate and none of them is what someone
    means by "the wallpaper looks wrong now".
  * reset: background, glow, effects, widgets — on every screen.

So the tests are mostly about what the reset must NOT reach, plus the
backup that makes a misclick survivable. A reset that quietly grew to
clear presets would still "work"; nothing would fail, and the user would
simply lose data.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import emit  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BRIDGE = (REPO / "wallpaper_bridge" / "bridge.py").read_text(encoding="utf-8")
CONF = (REPO / "wallpaper_bridge" / "configurator.html").read_text(encoding="utf-8")

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        emit(f"  ok    {label}")
    else:
        failed += 1
        emit(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def method_source(name):
    """Source of a method by name, via AST so nested defs don't confuse it."""
    tree = ast.parse(BRIDGE)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(BRIDGE, node) or ""
    return ""


def method_code(name):
    """Executable statements only — the docstring is stripped.

    The scope checks below look for words like "presets" and "library".
    Those legitimately appear in the docstring, which explains what the
    reset deliberately leaves alone; matching against the raw source
    made every one of them fail on correct code.
    """
    tree = ast.parse(BRIDGE)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            stmts = node.body
            if (stmts and isinstance(stmts[0], ast.Expr)
                    and isinstance(stmts[0].value, ast.Constant)
                    and isinstance(stmts[0].value.value, str)):
                stmts = stmts[1:]
            return "\n".join(ast.get_source_segment(BRIDGE, s) or "" for s in stmts)
    return ""


def main():
    emit("\nReset all screens\n" + "=" * 68)

    body = method_source("reset_all_screens")
    code = method_code("reset_all_screens")
    check("reset_all_screens exists", bool(body))

    # --- it must actually reset every screen ---------------------------
    check("it loops over every screen",
          "for sc in range(N_SCREENS)" in code,
          "resetting only the active screen is the old behaviour")
    check("it delegates to reset_screen",
          "self.reset_screen(sc)" in code,
          "a second implementation would drift from the per-screen one")

    # --- scope: the things it must NOT touch ---------------------------
    # Each of these would be a silent data loss, not a crash.
    for forbidden, what in [
        ("presets", "preset slots"),
        ("profiles", "per-app profiles"),
        ("library", "the image library"),
        ("apiToken", "the API token"),
        ("language", "the language setting"),
        ("openrgb", "OpenRGB config"),
        ("mqtt", "MQTT config"),
        ("sacn", "sACN config"),
    ]:
        check(f"does not touch {what}",
              forbidden.lower() not in code.lower(),
              f"'{forbidden}' appears in the body of reset_all_screens")

    # It must not wipe the config wholesale either.
    check("does not clear the config dict",
          not re.search(r"self\.config\s*=\s*\{", code))
    check("does not delete the config file",
          "unlink" not in code and "os.remove" not in code)

    # --- the safety net -------------------------------------------------
    check("a backup is written first",
          "config_path()" in code and "write_text" in code,
          "a misclick must be recoverable")
    check("the backup is a separate file, not an overwrite",
          "with_name" in code,
          "writing to config_path() itself would destroy what it saves")
    check("the backup filename is timestamped",
          "strftime" in code,
          "a fixed name would overwrite the previous rescue copy")
    check("a failed backup does not abort the reset",
          re.search(r"except Exception[\s\S]{0,200}?continuing anyway", code)
          is not None,
          "the backup is a safety net, not a precondition")
    check("the backup is config only, not the full ZIP",
          "build_backup_zip" not in code,
          "the ZIP carries the whole image library, which is not at risk")

    # --- reachable from the UI ------------------------------------------
    # "system-action" must be on the WS command whitelist, or the message
    # is dropped before the dispatcher ever sees it — and the branch
    # below would look perfectly correct while nothing happened.
    check('"system-action" is an accepted WS command type',
          '"system-action"' in BRIDGE.split("def on_widget_command")[0],
          "the type list in the broadcaster gates every command")

    disp = re.search(r'if action == "reset-all-screens":\s*\n\s*(.+)', BRIDGE)
    check("the system-action dispatches it", bool(disp),
          "without the branch the button does nothing")

    # The branch must come before the tray-handler table, which answers
    # anything it does not recognise with "unknown action". Landing after
    # it would make the button a no-op with a log line and nothing else.
    at_branch = BRIDGE.find('if action == "reset-all-screens":')
    at_unknown = BRIDGE.find("unknown action")
    check("it is dispatched before the unknown-action fallback",
          at_branch > 0 and at_unknown > at_branch,
          f"branch@{at_branch} fallback@{at_unknown}")
    if disp:
        check("it calls reset_all_screens", "reset_all_screens()" in disp.group(1),
              disp.group(1).strip())

    # Both must live on the same class or self.… would raise at runtime.
    tree = ast.parse(BRIDGE)
    owner = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef):
                    owner[sub.name] = node.name
    check("reset_all_screens sits beside reset_screen",
          owner.get("reset_all_screens") == owner.get("reset_screen")
          and owner.get("reset_screen") is not None,
          f"{owner.get('reset_all_screens')} vs {owner.get('reset_screen')}")

    # --- the button ------------------------------------------------------
    check("a reset button exists", 'id="sys-reset-all"' in CONF)
    check("it is styled as destructive", 'class="btn danger" id="sys-reset-all"' in CONF)
    check("it asks before firing",
          re.search(r'confirm\(t\("system\.reset_all_confirm"\)\)', CONF) is not None,
          "an unconfirmed destructive button is a trap")
    check("it sends the system-action",
          re.search(r'action: "reset-all-screens"', CONF) is not None)
    check("it is NOT in actionMap",
          not re.search(r'"sys-reset-all":\s*"reset-all-screens"', CONF),
          "actionMap entries fire immediately, bypassing the confirmation")

    for key in ("system.reset_all", "system.reset_all_hint",
                "system.reset_all_confirm", "system.reset_all_done"):
        entry = re.search(r'"%s":\s*\{[\s\S]{0,900}?\},' % re.escape(key), CONF)
        check(f"{key} is translated in both languages",
              bool(entry) and 'en: "' in entry.group(0) and 'de: "' in entry.group(0))

    # The confirmation has to say what survives, or "reset all" reads as
    # "erase everything" and nobody dares press it.
    conf_entry = re.search(r'"system\.reset_all_confirm":\s*\{[\s\S]{0,900}?\},', CONF)
    if conf_entry:
        text = conf_entry.group(0)
        check("the confirmation says presets are kept",
              "Presets" in text and "Voreinstellungen" in text)
        check("the confirmation mentions the backup",
              "saved first" in text and "gesichert" in text)

    emit("\n" + "=" * 68)
    emit(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
