"""A Quick Look must never overwrite a user's preset.

WHY THIS EXISTS

Reported as "habe ein Preset gespeichert, dann ein Quick Look ausgewählt,
seitdem ist das Preset überschrieben".

Since v1.2.16 every Quick Look saved the screen's previous state into
Preset slot 1 (`snapshotSlot: 0`), announced only by a toast. Whatever
the user had saved there was gone. Two other features read the same
slot and inherited the damage:

  * per-app profiles that apply "Preset 1" when a game starts
  * the Ctrl+Shift+1 preset hotkey

The previous state now goes into a separate per-screen `lookUndo` slot,
offered as "Undo last Quick Look". Presets are written only by the user.

The scenario is EXECUTED against the real BridgeRuntime methods, with
config persistence stubbed out so the test can never write the user's
real config file.
"""

import copy
import pathlib
import re
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from harness import emit, load_bridge  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = (REPO / "wallpaper_bridge" / "bridge.py").read_text(encoding="utf-8")
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


def make_runtime(b):
    saved = []
    b.save_config = lambda cfg: saved.append(cfg)      # never touch disk
    rt = object.__new__(b.BridgeRuntime)
    rt.config_lock = threading.RLock()
    screen = copy.deepcopy(b.DEFAULT_SCREEN_SETTINGS)
    rt.config = {"screens": {"0": screen, "1": copy.deepcopy(screen)}}
    rt.pushed = []
    rt.push_settings = lambda sc, snap: rt.pushed.append((sc, snap))
    rt._replicate_to_mirrors = lambda sc: None
    rt._block_if_mirror = lambda sc, what: False
    return rt, saved


def main():
    b = load_bridge()
    emit("\nQuick Look vs. presets (executed)\n" + "=" * 68)

    rt, saved = make_runtime(b)
    live = rt.config["screens"]["0"]

    # The user's own look, saved as Preset 1.
    live["glowStrength"] = 42
    live["ambientEffect"] = "snow"
    live["widgets"] = [{"id": "w1", "type": "clock", "x": 1, "y": 2, "w": 3, "h": 4,
                        "options": {}}]
    rt.save_preset(0, 0)
    mine = copy.deepcopy(live["presets"][0])
    check("the user's preset is saved", mine and mine.get("glowStrength") == 42)

    # The user keeps tweaking after saving. Without this step the live
    # state equals the preset, an overwrite is invisible, and the test
    # passes against the very bug it exists for (it did, first time).
    live["glowStrength"] = 55
    live["ambientEffect"] = "rain"

    # The reported action: pick a Quick Look.
    rt.quick_look_apply(0, settings={"glowStrength": 100, "ambientEffect": "aurora"},
                        widgets=[{"type": "calendar"}])
    check("the look was applied", live["glowStrength"] == 100 and
          live["ambientEffect"] == "aurora")
    check("Preset 1 is untouched by the Quick Look",
          live["presets"][0] == mine,
          "the reported bug: the auto-snapshot overwrote the user's preset")
    check("no other preset slot was filled either",
          all(p is None for p in live["presets"][1:]))
    check("the undo slot holds the state right before the Quick Look",
          isinstance(live.get("lookUndo"), dict) and
          live["lookUndo"].get("glowStrength") == 55 and
          live["lookUndo"].get("ambientEffect") == "rain",
          "the tweaked state, not the older preset")

    # Per-app profiles and the hotkey apply Preset 1 -- they must get the
    # user's look, not the pre-Quick-Look auto-snapshot.
    rt.apply_preset(0, 0)
    check("applying Preset 1 (profile / hotkey) restores the user's look",
          live["glowStrength"] == 42 and live["ambientEffect"] == "snow" and
          live["widgets"][0]["id"] == "w1")

    # Undo.
    rt.quick_look_apply(0, settings={"glowStrength": 77}, widgets=[])
    rt.undo_quick_look(0)
    check("undo restores the state before the last Quick Look",
          live["glowStrength"] == 42 and live["widgets"] and
          live["widgets"][0]["id"] == "w1")
    check("undo forgets the saved state, so a second click does nothing",
          live.get("lookUndo") is None)
    before = copy.deepcopy(live)
    rt.undo_quick_look(0)
    check("a second undo changes nothing", live == before)
    check("undo leaves presets alone", live["presets"][0] == mine)

    # Two Quick Looks in a row: undo goes back one step, to the look the
    # user was actually looking at, not to the original.
    rt.quick_look_apply(0, settings={"glowStrength": 60}, widgets=[])
    rt.quick_look_apply(0, settings={"glowStrength": 90}, widgets=[])
    rt.undo_quick_look(0)
    check("after two Quick Looks, undo returns to the first one",
          live["glowStrength"] == 60)

    # The undo state must never end up inside a preset, or saving a
    # preset would nest snapshots inside snapshots.
    rt.quick_look_apply(0, settings={"glowStrength": 10}, widgets=[])
    rt.save_preset(0, 2)
    check("a saved preset does not carry the undo state",
          "lookUndo" not in live["presets"][2])
    check("the per-screen state is isolated",
          rt.config["screens"]["1"].get("lookUndo") is None)
    check("persistence went through the stub, not the real config file",
          len(saved) > 0, "if this is 0, save_config was not intercepted")

    emit("\nwiring\n" + "=" * 68)
    check("lookUndo has a default", re.search(r'"lookUndo":\s+None', SRC) is not None)
    check("lookUndo is not part of a preset",
          '"lookUndo"' not in SRC[SRC.index("PRESET_SNAPSHOT_KEYS = ("):
                                  SRC.index(")", SRC.index("PRESET_SNAPSHOT_KEYS = ("))])
    nm = SRC[SRC.index("_NON_MIRRORED_KEYS = frozenset({"):]
    check("lookUndo is not copied to mirror screens",
          '"lookUndo"' in nm[:nm.index("})")])
    check("lookUndo cannot be set through setting-update",
          '"lookUndo"' not in SRC[SRC.index("_SETTABLE_SCREEN_KEYS = {"):
                                  SRC.index("}", SRC.index("_SETTABLE_SCREEN_KEYS = {"))])
    check("the undo message is routed",
          '"quick-look-undo"' in SRC and "self.undo_quick_look(screen)" in SRC)
    check("the bridge no longer accepts a preset slot for Quick Looks",
          "snapshot_slot" not in SRC and "snapshotSlot" not in SRC)
    apply = CONF[CONF.index("function applyLookBundle"):]
    apply = apply[:apply.index("\n}\n")]
    check("the Configurator asks for an undo snapshot, not a preset slot",
          "undoSnapshot: true" in apply and "snapshotSlot" not in apply)
    check("the toast no longer claims Preset slot 1",
          '"looks.autosnapshot"' not in CONF)
    # Two toasts in a row went into one element, so the first was never
    # readable. One toast now carries Undo directly.
    check("applying a look shows ONE toast, with Undo on it",
          apply.count("toast(") == 1 and "_undoLastLook" in apply)
    check("there is an undo button", 'id="looks-undo"' in CONF and
          'sendCmd({ type: "quick-look-undo" })' in CONF)
    check("it is only enabled when there is something to undo",
          "els.looksUndo.disabled = !settings.lookUndo;" in CONF)
    els_at = CONF.index("const els = {")
    check("the undo listener is registered after `const els` (TDZ)",
          CONF.index("els.looksUndo.addEventListener") > els_at)

    emit("\n" + "=" * 68)
    emit(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
