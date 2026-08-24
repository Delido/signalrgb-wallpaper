"""An older wallpaper bundle must keep working, and keep quiet about it.

WHY THIS EXISTS

`WALLPAPER_VERSION` goes up whenever anything under `wallpaper/`
changes, which is often and usually cosmetic. The bridge treated every
one of those as "your bundle is out of date" and pushed a banner onto
the desktop — four times during the 2.4.4 beta run alone, each time for
a page that was working perfectly.

That banner is on the *desktop*. There is no close button on a
wallpaper. So the question it answers has to be worth interrupting for,
and "a newer bundle exists" is not: an older page ignores unknown
setting keys (applyProperty's switch has no default branch) and unknown
message types, so it goes on doing exactly what it did before.

`MIN_WALLPAPER_VERSION` answers the narrower question — is the page too
old to *work*? Below it, the banner stands. Above it but behind
current, the Configurator and the log mention it and the wallpaper stays
clean.

The risk in this change is the inverse of the old behaviour: a bump that
should have raised the floor and did not, leaving a genuinely broken
page silent. So the tests pin both directions, and that the floor is
never ahead of the shipped bundle.
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
PAGE = (REPO / "wallpaper_bridge" / "wallpaper" / "index.html").read_text(encoding="utf-8")

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        emit(f"  ok    {label}")
    else:
        failed += 1
        emit(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def const(name):
    m = re.search(r'^%s\s*=\s*"([^"]+)"' % name, BRIDGE, re.M)
    return m.group(1) if m else None


def parse_version_fn():
    """The bridge's own _parse_version, so ordering is compared the way
    the bridge compares it rather than by a second implementation."""
    tree = ast.parse(BRIDGE)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_parse_version":
            src = ast.get_source_segment(BRIDGE, node)
            ns = {"re": re}
            # _parse_version leans on a helper for prerelease ordering.
            for helper in tree.body:
                if (isinstance(helper, ast.FunctionDef)
                        and helper.name == "_prerelease_key"):
                    exec(compile(ast.get_source_segment(BRIDGE, helper),
                                 "<h>", "exec"), ns)
            exec(compile(src, "<v>", "exec"), ns)
            return ns["_parse_version"]
    return None


def main():
    emit("\nWallpaper bundle compatibility\n" + "=" * 68)

    cur = const("WALLPAPER_VERSION")
    floor = const("MIN_WALLPAPER_VERSION")
    check("WALLPAPER_VERSION is declared", bool(cur), str(cur))
    check("MIN_WALLPAPER_VERSION is declared", bool(floor), str(floor))

    pv = parse_version_fn()
    check("the bridge's version parser was extracted", pv is not None)

    if cur and floor and pv:
        # The floor must never exceed what the installer ships, or every
        # fresh install would light up the banner it is meant to prevent.
        check("the floor is not ahead of the shipped bundle",
              pv(floor) <= pv(cur), f"min={floor} current={cur}")

        # --- the decision, run the way the bridge runs it ---
        def banner(bundle):
            """True when the bridge would push version-mismatch."""
            if not bundle or bundle == "dev":
                return False
            if pv(bundle) >= pv(cur):
                return False
            return pv(bundle) < pv(floor)

        check("the current bundle gets no banner", not banner(cur))
        check("a newer bundle gets no banner", not banner("99.0.0"))
        check("an unstamped dev tree gets no banner", not banner("dev"))
        check("a bundle exactly at the floor gets no banner", not banner(floor),
              f"{floor} is supported, not broken")
        check("a bundle below the floor still gets the banner",
              banner("0.1.0"), "a genuinely broken page must say so")

        # The case this change exists for: behind current, at or above
        # the floor. This is what used to interrupt the desktop.
        between = None
        for cand in ("2.4.0", "2.4.11", "2.4.12", "2.4.13"):
            if pv(floor) <= pv(cand) < pv(cur):
                between = cand
                break
        check("found a version between the floor and current", bool(between),
              f"floor={floor} current={cur}")
        if between:
            check(f"an older-but-supported bundle ({between}) gets no banner",
                  not banner(between),
                  "this is the case that used to put a banner on the desktop")

    # --- the bridge side ---
    fn = re.search(r"async def _on_hello\(.*?\n(?=    async def |    def )",
                   BRIDGE, re.S)
    check("_on_hello found", bool(fn))
    if fn:
        body = fn.group(0)
        check("the floor gates the banner", "MIN_WALLPAPER_VERSION" in body,
              "without it every bump interrupts the desktop again")
        # Naming the constant is not the same as acting on it. The guard
        # has to short-circuit, or the code reads correctly and still
        # pushes a banner for every bump — the exact behaviour this
        # change removes. A mutation that neutered the condition slipped
        # past an earlier version of this test.
        check("the guard returns for a supported bundle",
              re.search(r"min_t is not None and wp_t >= min_t:.*?return",
                        body, re.S) is not None,
              "the condition must short-circuit, not merely be present")
        check("the guard is not disabled",
              not re.search(r"if False:|if 0:", body),
              "a hard-coded false condition passes every name check")
        check("a supported-but-older bundle is logged instead",
              "no banner" in body,
              "it has to be recorded somewhere or nobody can diagnose it")
        check("the reported version is remembered",
              "client_wallpaper_versions" in body)

    # A table keyed by writer has to be cleaned up with the writer, or a
    # long-running bridge reports pages that closed hours ago.
    check("the version table is cleared on disconnect",
          re.search(r"client_wallpaper_versions.*?\.pop\(writer", BRIDGE,
                    re.S) is not None)

    # --- what the Configurator shows instead ---
    check("health reports the current bundle version",
          '"wallpaper_version":' in BRIDGE)
    check("health reports the floor",
          '"wallpaper_version_min":' in BRIDGE)
    check("health reports what the pages run",
          '"pages_wallpaper_versions":' in BRIDGE)
    check("the Configurator renders a note", 'id="wallpaper-version-note"' in CONF)
    check("the note is driven by the health payload",
          "pages_wallpaper_versions" in CONF)
    # v2.5.0: both numbers are shown permanently. They are allowed to
    # drift on purpose now, so "which am I running?" needs an answer
    # that does not involve the tray's About dialog — which was the only
    # place either number appeared.
    check("health reports the bridge version too", '"app_version":' in BRIDGE)
    check("the note names both versions",
          re.search(r'"system\.versions":\s*\{[\s\S]{0,300}?\{app\}[\s\S]{0,200}?\{wallpaper\}',
                    CONF) is not None,
          "one number alone does not answer the question")
    check("the version line is always visible",
          re.search(r'id="wallpaper-version-note"[\s\S]{0,80}?style="margin-top',
                    CONF) is not None,
          "it must not start hidden any more")
    check("the mismatch warning is styled apart from the line",
          '.hint .warn' in CONF and 'class="warn"' in CONF,
          "the factual line and the warning must be distinguishable")
    check("the warn colour is not danger red",
          re.search(r"--warn:\s*#(?!ff7575)", CONF) is not None,
          "an older-but-working bundle is not an error")

    check("only the warning is conditional, not the whole line",
          re.search(r"if \(stale\.length\)", CONF) is not None,
          "the version line itself stays regardless")
    check("the note is translated in both languages",
          re.search(r'"system\.bundle_outdated":\s*\{[\s\S]{0,600}?en:[\s\S]{0,400}?de:',
                    CONF) is not None)

    # --- and why an older page keeps working at all ---
    # These two are the actual compatibility guarantee. If either
    # changes, "older bundles keep working" stops being true and the
    # floor becomes the only protection.
    # Brace-matched rather than regex-bounded. The function is long, and
    # a `.*?\n  \}` stop lands 861 characters in, on the first nested
    # close — a mutation that added a throwing default branch sat
    # outside that window and went unnoticed.
    def _fn_body(src, needle):
        at = src.find(needle)
        if at < 0:
            return ""
        i = src.index("{", at)
        depth = 0
        for j in range(i, len(src)):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    return src[i:j + 1]
        return ""

    prop_body = _fn_body(PAGE, "function applyProperty(name, val)")
    check("applyProperty found", bool(prop_body))
    if prop_body:
        check("the whole function body was captured", len(prop_body) > 5000,
              f"{len(prop_body)} chars — a short match means a truncated window")
        check("unknown setting keys are ignored, not fatal",
              not re.search(r"\n\s*default:", prop_body),
              "a default branch would make older pages throw on new keys")
    check("unknown message types are ignored by the page",
          PAGE.count("msg.type ===") >= 4,
          "the chain of else-ifs simply falls through")

    emit("\n" + "=" * 68)
    emit(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
