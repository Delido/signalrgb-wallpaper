"""The UI language must be selectable, and the choice must survive.

WHY THIS EXISTS

Everything needed to switch languages has been in the bridge for many
versions: a validated `language` config field ("auto" | "en" | "de"),
`init_language()` to resolve it, a full TRANSLATIONS table on both
sides. The one missing piece was any way to *write* the field — no
control in the Configurator, no tray item — so choosing a language meant
editing config.json by hand and restarting.

Reported as: "es sollte einstellbar sein ob man deutsch oder englisch
haben will".

Four things have to hold, and each is a separate way to end up with a
picker that looks fine and does nothing:

  * "language" is on the bridge's settable whitelist. Without the entry
    the WS dispatch drops the update *silently* — the exact symptom the
    openrgbSdkServer comment in that whitelist already records.
  * bad values are rejected rather than persisted, or the UI ends up in
    a language with no translation table.
  * the resolver runs again on change, so it applies without a restart.
  * _get_bridge_state echoes the stored preference, not the resolved
    language — otherwise "auto" would display as "German" as soon as it
    round-trips, and the user could never get back to automatic.
"""

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


def main():
    emit("\nLanguage setting\n" + "=" * 68)

    # --- the bridge must accept the key ---------------------------------
    wl = re.search(r"_SETTABLE_BRIDGE_KEYS\s*=\s*\{(.*?)\n    \}", BRIDGE, re.S)
    check("_SETTABLE_BRIDGE_KEYS found", bool(wl))
    if wl:
        keys = re.findall(r'"(\w+)"', wl.group(1))
        check('"language" is whitelisted', "language" in keys,
              "without it the WS dispatch drops the update silently")

    # --- and handle it ---------------------------------------------------
    branch = re.search(r'elif key == "language":(.*?)\n        elif ', BRIDGE, re.S)
    check("language branch exists in update_bridge_setting", bool(branch))
    if branch:
        body = branch.group(1)
        check("only auto/en/de are accepted",
              re.search(r'not in \("auto", "en", "de"\)', body) is not None,
              "an unvalidated value would leave the UI without a table")
        check("a rejected value returns without persisting",
              re.search(r"not recognised[\s\S]{0,80}return", body) is not None)
        check("the choice is persisted", "save_config(snapshot)" in body)
        check("the resolver runs again so no restart is needed",
              "init_language(snapshot)" in body,
              "config alone does not change _CURRENT_LANG")
        check("connected pages are re-pushed", "push_settings" in body)

    # init_language must actually exist under that name — an invented
    # helper name would only fail at runtime, on the click.
    check("init_language is a real function",
          re.search(r"^def init_language\(", BRIDGE, re.M) is not None)
    check("no call to a non-existent apply_language",
          "apply_language(" not in BRIDGE)

    # --- the picker needs a value to show --------------------------------
    state = re.search(r"def _get_bridge_state.*?\n        with self\.config_lock:\n"
                      r"            return \{(.*?)\n            \}", BRIDGE, re.S)
    check("_get_bridge_state body found", bool(state))
    if state:
        check("bridge state includes language", '"language"' in state.group(1),
              "the picker would render empty")
        # The stored preference, not the resolved value: echoing
        # _CURRENT_LANG makes "auto" come back as "de" and the user can
        # never return to automatic.
        lang_line = re.search(r'"language":\s*([^\n]+)', state.group(1))
        check("it echoes the stored preference, not _CURRENT_LANG",
              bool(lang_line) and "_CURRENT_LANG" not in lang_line.group(1),
              lang_line.group(1) if lang_line else "")
        check('it defaults to "auto"',
              bool(lang_line) and '"auto"' in lang_line.group(1),
              lang_line.group(1) if lang_line else "")

    # --- the Configurator side -------------------------------------------
    check("a language <select> exists", 'id="sys-language"' in CONF)
    for value in ("auto", "en", "de"):
        check(f'option "{value}" is offered',
              re.search(r'<option value="%s"' % value, CONF) is not None)
    check("the select sends a bridge-setting-update",
          re.search(r'key: "language", value: langSel\.value', CONF) is not None)
    check("the select is populated from bridgeState",
          re.search(r'langSel\.value = bridgeState\.language', CONF) is not None)
    check("its label is translated in both languages",
          re.search(r'"system\.language":\s*\{[^}]*en:[^}]*de:[^}]*\}', CONF) is not None)
    check('the "automatic" option is translated too',
          re.search(r'"system\.language\.auto":\s*\{[^}]*en:[^}]*de:[^}]*\}', CONF)
          is not None)

    # The config default must stay "auto" — a fresh install should follow
    # the OS rather than pinning English.
    check('config default for language is "auto"',
          re.search(r'"language":\s*"auto"', BRIDGE) is not None)

    emit("\n" + "=" * 68)
    emit(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
