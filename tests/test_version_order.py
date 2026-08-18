"""Version comparison for the update checker.

THE BUG THIS EXISTS FOR

`_parse_version` returned the prerelease label as a plain string, so the
tuples were compared character by character:

    "beta.9"  vs  "beta.10"   ->  "9" > "1"  ->  beta.9 wins

From v2.4.4-beta.10 onwards the tray's update check therefore offered
beta.9 as the newest build, and every release after it was invisible.
Reported as "the tray doesn't find beta.11, it only offers me beta.9".

Semver compares dot-separated identifiers field by field, numeric ones
numerically. These tests pin that, plus the orderings around it that a
naive fix would break — prerelease below stable, beta below rc.

Run: python tests/test_version_order.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Results, emit  # noqa: E402

# Import the two helpers WITHOUT importing bridge.py: it pulls in
# pystray/Pillow/tkinter and hijacks stdout, none of which this needs.
_SRC = (Path(__file__).resolve().parent.parent
        / "wallpaper_bridge" / "bridge.py").read_text(encoding="utf-8")
_ns = {"re": re}
exec(_SRC[_SRC.index("def _prerelease_key"):_SRC.index("class UpdateChecker")], _ns)
parse = _ns["_parse_version"]


def main():
    r = Results("version order")

    emit("\nthe reported bug: beta.9 outranked every later beta")
    for a, b in [("2.4.4-beta.9", "2.4.4-beta.10"),
                 ("2.4.4-beta.9", "2.4.4-beta.11"),
                 ("2.4.4-beta.9", "2.4.4-beta.12"),
                 ("2.4.4-beta.11", "2.4.4-beta.12")]:
        r.check(f"{a} < {b}", parse(a) < parse(b))

    # The exact scenario from the report: current build is beta.11, and
    # the API returns every release. The picker must land on the newest,
    # not on whichever sorts highest as a string.
    emit("\npicking the newest release out of a real list")
    releases = ["v2.4.2", "v2.4.3", "v2.4.4-beta.9", "v2.4.4-beta.10",
                "v2.4.4-beta.11", "v2.4.4-beta.12"]
    newest = max(releases, key=parse)
    r.check("newest of the beta line is beta.12", newest == "v2.4.4-beta.12", newest)
    r.check("beta.11 sees beta.12 as an update",
            parse("v2.4.4-beta.12") > parse("2.4.4-beta.11"))
    r.check("beta.11 does NOT see beta.9 as an update",
            parse("v2.4.4-beta.9") < parse("2.4.4-beta.11"))

    emit("\nsemver orderings a naive fix would break")
    r.check("a prerelease sorts below its stable release",
            parse("2.4.4-beta.12") < parse("2.4.4"))
    r.check("beta sorts below rc", parse("2.4.4-beta.2") < parse("2.4.4-rc.1"))
    r.check("numeric identifiers sort below alphanumeric ones",
            parse("2.4.4-1") < parse("2.4.4-alpha"))
    r.check("a newer minor beats an older stable",
            parse("2.4.4") < parse("2.5.0-beta.1"))
    r.check("patch level still counts", parse("2.4.3") < parse("2.4.4"))
    r.check("major level still counts", parse("2.9.9") < parse("3.0.0"))

    emit("\nmalformed input cannot fake an update")
    # A garbage tag must never outrank a real version, or a stray
    # release name would push a bogus "update available" at everyone.
    for junk in ("", "latest", "v", "2.4", "not-a-version", None):
        r.check(f"{junk!r} sorts below a real version",
                parse(junk) < parse("0.0.1"))

    emit("\nthe shipped constants parse")
    for name in ("APP_VERSION", "WALLPAPER_VERSION"):
        m = re.search(rf'^{name}\s*=\s*"([^"]+)"', _SRC, re.M)
        r.check(f"{name} is present", bool(m))
        if m:
            # (0,0,0,...) is the garbage sentinel — the app's own
            # version scoring as garbage would break update checks
            # entirely.
            r.check(f"{name} = {m.group(1)} parses to a real version",
                    parse(m.group(1))[:3] != (0, 0, 0), str(parse(m.group(1))))

    emit("")
    return 0 if r.summary() else 1


if __name__ == "__main__":
    sys.exit(main())
