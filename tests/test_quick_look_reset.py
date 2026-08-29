"""A Quick Look must define a complete visual state, not a partial one.

WHY THIS EXISTS

Reported as "die anderen Looks setzen Pure black nicht wieder zurueck":
after applying the Ambilight look, switching to any other look left the
background pure black. Only the Ambilight bundle names `ambientMode`,
and applyLookBundle sends only the keys a bundle actually lists, so
nothing ever turned it off again.

An audit of the bundles found the same latent bug in two more keys the
same commit introduced -- `gridBlur: 260` and `pixelfx: "off"` -- and
`barLayout`, which the `minimal` bundle has never set.

The general shape: any key that some bundles set and others do not
sticks when the user switches between them. The result then depends on
the order things were clicked, so "Cyberpunk after Ambilight" and
"Cyberpunk on a fresh screen" are different screens. That is the bug,
not the individual keys.

quick_look_apply now resets every key in QUICK_LOOK_VISUAL_KEYS that
the bundle does not mention back to its default. This test pins the two
halves that can drift apart:

  * every key any bundle sets is covered by the tuple (or the bug is
    back for that key), and
  * the tuple does not reach beyond what looks own -- resetting a
    setting no look touches would wipe a user's own configuration.
"""

import ast
import copy
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


def bundle_keys():
    """Every settings key any Quick Look bundle sets, read from the
    shipped Configurator rather than restated here -- a hard-coded list
    would go stale the moment a bundle changes, which is the very
    failure this test exists to catch."""
    start = CONF.index("const LOOK_BUNDLES = [")
    end = CONF.index("\n];", start)
    body = CONF[start:end]
    keys = set()
    per_bundle = {}
    for m in re.finditer(r'id:\s*"([^"]+)"', body):
        bid = m.group(1)
        sm = re.search(r'settings:\s*\{(.*?)\n    \}', body[m.start():], re.S)
        if not sm:
            continue
        ks = set(re.findall(r'^\s{6}(\w+):', sm.group(1), re.M))
        per_bundle[bid] = ks
        keys |= ks
    return keys, per_bundle


def tuple_keys(name):
    m = re.search(name + r"\s*=\s*\((.*?)\n\)", BRIDGE, re.S)
    return set(re.findall(r'"(\w+)"', m.group(1))) if m else set()


def defaults_keys():
    m = re.search(r"DEFAULT_SCREEN_SETTINGS = \{(.*?)\n\}", BRIDGE, re.S)
    return set(re.findall(r'^\s{4}"(\w+)":', m.group(1), re.M))


def main():
    emit("\nQuick Look completeness\n" + "=" * 68)

    used, per_bundle = bundle_keys()
    declared = tuple_keys("QUICK_LOOK_VISUAL_KEYS")
    defaults = defaults_keys()

    check("the bundles were parsed", len(per_bundle) >= 8,
          f"found {len(per_bundle)}")
    check("QUICK_LOOK_VISUAL_KEYS is declared", bool(declared))

    # --- half one: nothing a bundle sets may be left out ---------------
    # This is the reported bug, generalised. A key here means switching
    # away from the bundle that sets it leaves it behind.
    missing = used - declared
    check("every key a bundle sets is reset when absent",
          not missing,
          f"not covered: {sorted(missing)} — these stick when the user "
          f"switches looks")

    # --- half two: and nothing beyond that ----------------------------
    # The inverse mistake, which is worse because it is silent: resetting
    # a setting no look owns wipes something the user configured. The
    # concrete candidates are effectQuality (documented as the user's own
    # perf trade-off), mouseEffects, widgetTheme, barHeight/barWidth and
    # stripesBlur -- all of which travel with PRESETS, a different
    # mechanism.
    extra = declared - used
    check("no key beyond what the looks own is reset",
          not extra,
          f"would be wiped without any look asking: {sorted(extra)}")

    # A key with no default cannot be reset; it would be skipped at
    # runtime and the coverage above would be a false promise.
    nodefault = declared - defaults
    check("every declared key has a default to fall back to",
          not nodefault, f"no default: {sorted(nodefault)}")

    # --- the exclusions, stated as intent ------------------------------
    # These are the two promises the reset must not break.
    for key in ("bgImage", "bgImageUrl", "bgFit", "bgDim", "bgTileScale"):
        check(f"{key} is never reset by a look",
              key not in declared,
              "the user's wallpaper survives a Quick Look")
    for key in ("gridRenderer", "glassQuality", "frameRate"):
        check(f"{key} is never reset by a look",
              key not in declared,
              "hardware-perf preferences belong to the user")
    for key in ("widgets", "presets", "cycle", "mirrorOf", "monitorSetup"):
        check(f"{key} is not in the visual reset",
              key not in declared,
              "structural state has its own dispatch path")

    # --- the reset actually runs ---------------------------------------
    fn_at = BRIDGE.index("def quick_look_apply")
    fn_end = BRIDGE.index("\n    def ", fn_at + 10)
    fn = BRIDGE[fn_at:fn_end]
    check("quick_look_apply backfills the defaults",
          "QUICK_LOOK_VISUAL_KEYS" in fn,
          "without this the tuple is documentation, not behaviour")
    # Naming the tuple is not using it. The backfill has to write into
    # the settings dict, and it has to skip keys the bundle DID set --
    # otherwise a look could never set anything at all.
    check("it only fills keys the bundle left out",
          re.search(r"if key in settings or key not in DEFAULT_SCREEN_SETTINGS:\s*\n\s*continue",
                    fn) is not None,
          "without the `key in settings` guard the bundle's own values "
          "are overwritten by defaults and every look becomes identical")
    check("it writes the default into the payload",
          re.search(r"settings\[key\] = copy\.deepcopy\(DEFAULT_SCREEN_SETTINGS\[key\]\)",
                    fn) is not None)
    # Mutable defaults (lists, dicts) must be copied or every screen ends
    # up sharing one object with DEFAULT_SCREEN_SETTINGS.
    check("mutable defaults are deep-copied",
          "copy.deepcopy(DEFAULT_SCREEN_SETTINGS[key])" in fn,
          "a shared list would let one screen mutate the global default")
    # It has to happen BEFORE the whitelist loop, or the filled-in keys
    # are never applied.
    check("the backfill runs before the settings are applied",
          fn.index("QUICK_LOOK_VISUAL_KEYS") <
          fn.index("for key, value in settings.items()"),
          "filling in after the apply loop would change nothing")

    # --- the reported case, end to end ---------------------------------
    # Run the real decision for ambientMode against a bundle that does
    # not mention it, using the shipped tuple and defaults.
    check("ambientMode is covered", "ambientMode" in declared,
          "the reported bug: pure black stayed after switching looks")
    non_ambilight = [b for b, ks in per_bundle.items()
                     if b != "ambilight" and "ambientMode" not in ks]
    check("other bundles genuinely do not set it",
          len(non_ambilight) >= 5,
          "if they all set it the reset would be untested here")
    # And the two the same commit introduced.
    for key in ("gridBlur", "pixelfx"):
        check(f"{key} is covered too", key in declared,
              "same latent bug, found by auditing rather than by report")

    emit("\n" + "=" * 68)
    emit(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
