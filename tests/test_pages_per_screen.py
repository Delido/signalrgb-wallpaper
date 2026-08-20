"""pages_per_screen must count wallpaper pages, not every client.

WHY THIS EXISTS

The "assigned" setup step reads pages_per_screen to decide whether every
screen has a wallpaper running. The count included *every* WebSocket
client on a screen, and the Configurator is one of those — so on a
two-screen setup with the Configurator open on screen 1 the field read
[2, 1] rather than [1, 1].

That is wrong in both directions:

  * screen 1 is inflated, so a screen whose wallpaper has genuinely died
    still counts as fine as long as a Configurator tab is open on it
  * during startup the Configurator connects first, which is what made
    the setup banner appear and then clear itself a minute later once
    Lively had finished bringing the second page up

`pages_connected` next to it already filtered by role and has done since
the field was added; this one never did, and the comment on
`client_roles` in `Broadcaster.add` says outright that the side-table
exists "so the Status dialog can count only the actual wallpaper pages
and not e.g. the user's own open Configurator tab".

The counting block is executed here rather than pattern-matched: the
question is what number comes out for a given set of clients, which no
amount of reading the source answers directly.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from harness import emit  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = (REPO / "wallpaper_bridge" / "bridge.py").read_text(encoding="utf-8")

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        emit(f"  ok    {label}")
    else:
        failed += 1
        emit(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))


def counting_block():
    """The pages_per_screen loop, dedented so it can be exec'd."""
    start = SRC.find("roles = {}\n        if self.broadcaster:")
    if start < 0:
        return ""
    end = SRC.index("pages_per_screen.append(n)", start)
    end += len("pages_per_screen.append(n)")
    block = SRC[start:end]
    return "\n".join(l[8:] if l.startswith(" " * 8) else l
                     for l in block.split("\n"))


BLOCK = counting_block()


class _FakeBroadcaster:
    def __init__(self, clients, roles):
        self.clients_by_screen = clients
        self.client_roles = roles


def count(clients, roles, screen_count=2):
    holder = type("S", (), {"broadcaster": _FakeBroadcaster(clients, roles)})()
    ns = {"self": holder, "screen_count": screen_count, "getattr": getattr}
    exec(compile(BLOCK + "\n", "<pages_per_screen>", "exec"), ns)
    return ns["pages_per_screen"]


def main():
    emit("\npages_per_screen\n" + "=" * 68)
    check("the counting block was located", bool(BLOCK),
          "the loop moved or was rewritten")
    if not BLOCK:
        emit(f"\n{passed} passed, {failed} failed")
        return 1

    WP0, WP1, CFG, CFG2 = "wp0", "wp1", "cfg", "cfg2"

    # The reported case: wallpapers on both screens, Configurator open
    # on screen 1. Used to report [2, 1].
    got = count({0: {WP0, CFG}, 1: {WP1}},
                {WP0: "wallpaper", WP1: "wallpaper", CFG: "configurator"})
    check("an open Configurator does not count as a wallpaper page",
          got == [1, 1], f"got {got}, expected [1, 1]")

    # Two Configurator tabs on one screen must not mask a dead wallpaper.
    got = count({0: {CFG, CFG2}, 1: {WP1}},
                {WP1: "wallpaper", CFG: "configurator", CFG2: "configurator"})
    check("a screen with only Configurator tabs reports zero pages",
          got == [0, 1], f"got {got}, expected [0, 1]")

    # A genuinely unassigned screen must still be detected.
    got = count({0: {WP0}, 1: {CFG}},
                {WP0: "wallpaper", CFG: "configurator"})
    check("a screen with no wallpaper still reports zero",
          got == [1, 0], f"got {got}, expected [1, 0]")

    # Several wallpaper pages on one screen (span setups) still count.
    got = count({0: {WP0, "wp0b"}, 1: {WP1}},
                {WP0: "wallpaper", "wp0b": "wallpaper", WP1: "wallpaper"})
    check("multiple wallpaper pages on a screen are all counted",
          got == [2, 1], f"got {got}, expected [2, 1]")

    # No role table: fall back to the raw count rather than reporting
    # zero everywhere, which would fire the banner on every screen.
    got = count({0: {WP0}, 1: {WP1}}, {})
    check("without a role table it falls back to the raw count",
          got == [1, 1], f"got {got}, expected [1, 1]")

    # An unknown role defaults to wallpaper — an older client that never
    # announced itself should not be treated as missing.
    got = count({0: {WP0}, 1: {"mystery"}}, {WP0: "wallpaper"})
    check("an unregistered client counts as a wallpaper page",
          got == [1, 1], f"got {got}, expected [1, 1]")

    got = count({}, {})
    check("nothing connected reports zero for every screen",
          got == [0, 0], f"got {got}, expected [0, 0]")

    # And the neighbouring total must keep filtering the same way, or
    # the two fields disagree about the same install.
    check("pages_connected still filters by role",
          'if r == "wallpaper"' in SRC,
          "the two counts would then disagree")

    emit("\n" + "=" * 68)
    emit(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
