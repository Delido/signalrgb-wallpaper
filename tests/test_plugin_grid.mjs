// SignalRGB plugin: per-device grid state.
//
// THE BUG THIS EXISTS FOR
//
// `dimsDirty` was a single global boolean, but SignalRGB calls Render()
// once per DEVICE. Whichever device rendered first after a settings
// change consumed the flag; the other never saw it and silently kept
// its previous grid.
//
// Symptom: changing "Glow Grid Base Size" appeared to do nothing on one
// of two monitors while the other updated normally. Which one depended
// purely on the order SignalRGB happened to call Render() in — so it
// looked random, and the setting looked broken.
//
// Reported as "if I change the Glow Grid Base Size on Screen 1 nothing
// happens", alongside a visibly coarser glow on that monitor.
//
// The plugin runs in SignalRGB's QJSEngine sandbox and cannot be
// imported here (no `device`, no `controller`). These tests extract the
// dirty-flag machinery and run it against a fake two-device render
// loop, which is exactly the part that was wrong.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..");
const SRC = readFileSync(
  join(repo, "plugin", "SignalRGB_Desktop_Wallpaper.js"), "utf8");

const results = { passed: 0, failed: [] };
function check(label, cond, detail = "") {
  if (cond) { results.passed++; console.log(`  PASS  ${label}`); }
  else { results.failed.push(label); console.log(`  FAIL  ${label}${detail ? "  — " + detail : ""}`); }
}

console.log("\nthe dirty flag is per screen, not shared");
{
  // A single boolean cannot serve N devices: one consumes it, the rest
  // starve. This is the shape check; the behavioural proof is below.
  check("dimsDirty is a Set, not a boolean",
        /const dimsDirty = new Set\(\)/.test(SRC));
  check("no assignment back to a boolean",
        !/dimsDirty\s*=\s*(true|false)/.test(SRC));
  check("Render clears only the current screen's entry",
        /dimsDirty\.delete\(_screen\)/.test(SRC));
  check("Render tests only the current screen's entry",
        /dimsDirty\.has\(_screen\)/.test(SRC));
  check("a settings change marks every screen",
        /function dirtyAll\(\)/.test(SRC) &&
        /ongridSizeChanged\(\)\s*\{\s*dirtyAll\(\);/.test(SRC));
  // A viewport moving is per-screen news; marking all four would rebuild
  // grids that did not change on every /config poll.
  check("a viewport change marks only that screen",
        /dimsDirty\.add\(i\)/.test(SRC));
}

console.log("\nthe reported scenario, run against the real code");
{
  // Lift dirtyAll + the Set out of the source rather than restating
  // them — a local reimplementation would keep passing after a
  // regression in the file it is meant to guard.
  const setDecl = SRC.match(/const dimsDirty = new Set\(\);/);
  const fnDecl = SRC.match(/function dirtyAll\(\)[\s\S]*?\n\}/);
  check("dirty-flag machinery is extractable", !!setDecl && !!fnDecl);

  if (setDecl && fnDecl) {
    // eslint-disable-next-line no-new-func
    const mk = new Function("MAX_SCREENS",
      `${setDecl[0]}\n${fnDecl[0]}\nreturn { dimsDirty, dirtyAll };`);

    /** Two devices, a settings change, and N render passes. */
    function runScenario(order) {
      const { dimsDirty, dirtyAll } = mk(4);
      const grid = { 0: 32, 1: 32 };
      let pending = 32;
      const render = (s) => {
        if (dimsDirty.has(s)) { dimsDirty.delete(s); grid[s] = pending; }
      };
      // Settle the initial mark the plugin sets at load.
      dirtyAll();
      for (let f = 0; f < 2; f++) for (const d of order) render(d);
      // The user changes Glow Grid Base Size.
      pending = 64;
      dirtyAll();
      for (let f = 0; f < 2; f++) for (const d of order) render(d);
      return grid;
    }

    const forward = runScenario([0, 1]);
    check("screen 0 first: both devices pick up the new base size",
          forward[0] === 64 && forward[1] === 64, JSON.stringify(forward));
    // The old bug was order-dependent, so both orders have to be shown.
    const reverse = runScenario([1, 0]);
    check("screen 1 first: both devices pick up the new base size",
          reverse[0] === 64 && reverse[1] === 64, JSON.stringify(reverse));

    // Steady state must stay quiet: Render runs at 30-60 fps per device
    // and rebuilding the LED registry every frame would stall the
    // single-threaded sandbox.
    const { dimsDirty, dirtyAll } = mk(4);
    dirtyAll();
    let rebuilds = 0;
    const render = (s) => {
      if (dimsDirty.has(s)) { dimsDirty.delete(s); rebuilds++; }
    };
    for (let f = 0; f < 50; f++) for (const d of [0, 1]) render(d);
    check("no rebuild storm once settled (2 rebuilds over 50 frames)",
          rebuilds === 2, String(rebuilds));
  }
}

console.log("\ngrid geometry follows the monitor, not a fixed shape");
{
  // The user's grid was 128x36 — a 3.56:1 shape — on 16:9 monitors,
  // giving 20x40 px cells: twice as tall as wide, and coarse enough
  // that the 30px blur could not hide the block edges. That is an
  // Aspect Ratio setting left over from the earlier span layout, not a
  // code fault, but the derivation is worth pinning.
  const m = SRC.match(/function computeGridDimensions\(\)[\s\S]*?\n\}/);
  check("computeGridDimensions is present", !!m);
  if (m) {
    // eslint-disable-next-line no-new-func
    const make = (base, aspect, viewport) => new Function(
      "gridSizeValue", "aspectRatioValue", "customColsValue", "customRowsValue",
      "viewportsByScreen", "currentScreenIndex", "clampInt", "MAX_GRID",
      `${m[0]}; return computeGridDimensions();`)(
      () => base, () => aspect, () => 32, () => 32,
      viewport ? [viewport] : [], () => 0,
      (v, lo, hi) => Math.max(lo, Math.min(hi, v)), 128);

    const auto = make(36, "Auto", { w: 2560, h: 1440 });
    check("Auto on a 16:9 monitor gives square-ish cells",
          Math.abs((2560 / auto.cols) - (1440 / auto.rows)) < 1,
          `${auto.cols}x${auto.rows}`);
    const wide = make(36, "32:9", { w: 2560, h: 1440 });
    check("a 32:9 setting on a 16:9 monitor stretches the cells",
          Math.abs((2560 / wide.cols) - (1440 / wide.rows)) > 10,
          `${wide.cols}x${wide.rows} — the reported 128x36`);
    const finer = make(64, "Auto", { w: 2560, h: 1440 });
    check("a larger base size gives finer cells",
          finer.rows > auto.rows, `${finer.cols}x${finer.rows}`);
    check("the grid stays within the wire limit",
          finer.cols <= 128 && finer.rows <= 128);
  }
}

const total = results.passed + results.failed.length;
console.log(`\n  ${results.passed}/${total} passed`);
if (results.failed.length) {
  console.log("\n  failed:");
  for (const f of results.failed) console.log(`    - ${f}`);
}
process.exit(results.failed.length ? 1 : 0);
