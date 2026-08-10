// Effect tiles in the Configurator must resemble the real effect.
//
// The picker renders a live miniature of each ambient preset, but from a
// SECOND implementation: TILE_PRESETS in configurator.html, separate from
// AMBIENT_PRESETS in wallpaper/index.html. Two copies of the same idea,
// free to drift.
//
// They did drift, and it hid a real bug. aurora and plasma shipped with
// peak alpha 0.14 / 0.18 in the wallpaper while their tiles used
// 0.4 / 0.35. The tiles looked lively; on the desktop both effects were
// invisible. Users reported them as "no different from off", and the
// preview that existed specifically to show what an effect looks like
// was concealing the problem.
//
// HOW THIS TEST WORKS
//
// The first version of this file compared the two tables with regexes
// over the source. That only worked for the two presets whose alpha is a
// literal (`const a = 0.34`); the other thirteen compute it, and
// `a: 0.5 + Math.random()*0.3` is not something a regex can evaluate.
// Those thirteen silently counted as passes, so the suite reported all
// green while actually measuring four of seventeen effects — and it
// could not even detect the aurora bug it was written for.
//
// So instead of reading the source, we run it: both tables are extracted
// and evaluated against a recording canvas that logs draw calls, and the
// checks below measure what each preset actually paints.
//
// WHAT IS COMPARED, AND WHY NOT COVERAGE
//
// Not total ink. A 160x100 tile is legitimately denser than a 5120x1440
// desktop — otherwise the thumbnail would read as empty — and aurora's
// blob radii do not scale down, so on a tile it covers the canvas many
// times over. Measured coverage ratios between the two sides run from
// 1.6x to 32x with no defect involved, which makes coverage useless as a
// pass/fail signal.
//
// What is comparable is the *alpha* each side paints with, measured at
// the same canvas size so area effects cancel. Across all 17 presets
// that ratio sits between 0.92x and 1.61x today. Anything far above that
// means the tile is advertising a strength the effect does not deliver.

import {
  CFG, WP, presetNames, loadTable, runPreset, effectiveAlpha,
} from "./preset_harness.mjs";

const results = { passed: 0, failed: [] };
function check(label, cond, detail = "") {
  if (cond) { results.passed++; console.log(`  PASS  ${label}`); }
  else { results.failed.push(label); console.log(`  FAIL  ${label}${detail ? "  — " + detail : ""}`); }
}

const SIZE = { w: 160, h: 100, frames: 300 };
const meanAlpha = (r) => {
  let sum = 0;
  for (const o of r.ops) sum += effectiveAlpha(o);
  return r.ops.length ? sum / r.ops.length : 0;
};

let wpTable, tileTable, names;
try {
  wpTable = loadTable(WP, "AMBIENT_PRESETS");
  tileTable = loadTable(CFG, "TILE_PRESETS");
  names = presetNames();
} catch (e) {
  console.log(`  FAIL  preset tables could not be loaded — ${e.message}`);
  process.exit(1);
}

console.log("\nboth implementations are present and complete");
{
  check("configurator defines TILE_PRESETS", Object.keys(tileTable).length > 0);
  check("wallpaper defines AMBIENT_PRESETS", Object.keys(wpTable).length > 0);
  // Every effect the picker offers must exist on both sides. `storm` was
  // absent from the old regex sweep entirely (it is built by an IIFE, not
  // an object literal) and so went unchecked for its whole life.
  const missingWp = names.filter((n) => !wpTable[n]);
  const missingTile = names.filter((n) => !tileTable[n]);
  check("every offered effect exists in the wallpaper", missingWp.length === 0, missingWp.join(", "));
  check("every offered effect has a tile preview", missingTile.length === 0, missingTile.join(", "));
}

console.log("\nevery effect runs without throwing");
const measured = {};
for (const n of names) {
  let ok = true, detail = "";
  try {
    measured[n] = {
      wp: runPreset(wpTable, n, { ...SIZE, density: 60, kind: "wallpaper" }),
      tile: runPreset(tileTable, n, { ...SIZE, kind: "tile" }),
    };
  } catch (e) { ok = false; detail = e.message.slice(0, 90); }
  check(`${n} — spawn/step/render survive 300 frames`, ok, detail);
}

console.log("\nevery effect actually paints something");
for (const n of names) {
  const m = measured[n];
  if (!m) continue;
  // A preset that records zero draws is either dead or mis-driven. Both
  // are worth failing on: "renders nothing" is exactly the class of bug
  // that reached users in aurora's case.
  check(`${n} — wallpaper draws at least one op`, m.wp.ops.length > 0);
  check(`${n} — tile draws at least one op`, m.tile.ops.length > 0);
}

console.log("\nthe picker previews what the effect actually looks like");
for (const n of names) {
  const m = measured[n];
  if (!m || !m.wp.ops.length || !m.tile.ops.length) continue;
  const wpM = meanAlpha(m.wp);
  const tileM = meanAlpha(m.tile);
  const ratio = wpM ? tileM / wpM : Infinity;
  // 2.5x: today's spread tops out at 1.61x (flowfield), and the aurora
  // regression lands at 3.81x. The gap is wide enough that the threshold
  // is not finely balanced against either side.
  check(`${n} — tile is not far stronger than the effect ` +
        `(wp ${wpM.toFixed(3)}, tile ${tileM.toFixed(3)})`,
        ratio <= 2.5, `ratio ${ratio.toFixed(2)}x`);
}

console.log("\nthe soft presets stayed above the perceptual floor");
{
  // aurora and plasma composite over a photograph, not black. Below
  // roughly 0.25 peak they stop registering as a soft area of colour.
  // This is the check that catches a faint effect whose tile is equally
  // faint — the ratio test above cannot see that case, and plasma's
  // historical bug is exactly it (ratio only 1.94x, but peak 0.18).
  for (const n of ["aurora", "plasma"]) {
    const m = measured[n];
    const a = m ? m.wp.peakAlpha : null;
    check(`${n} peak alpha is at least 0.25`, a !== null && a >= 0.25,
          a === null ? "not measured" : a.toFixed(3));
  }
}

console.log("\nlarge soft blobs don't pay for the square around the circle");
{
  // The corners of a 2r x 2r fill are alpha 0 but still get blended, and
  // they are 1 - pi/4 = 21 % of every fill. With v2.4.4's radius scaling
  // these blobs cover much of a wide desktop, so it is real fill rate.
  //
  // The check is "no square fills", not "uses arc()". Two ways to avoid
  // the corners are in use: arc() + fill() (aurora, plasma) and stamping
  // a pre-rendered sprite whose rim is already transparent (fireflies,
  // sparks — v2.4.5). An earlier version of this test demanded arc()
  // specifically and failed the sprite path, which is strictly better
  // than what it was asking for. Test the property, not the mechanism.
  for (const n of ["aurora", "plasma", "fireflies", "sparks"]) {
    const m = measured[n];
    if (!m) { check(`${n} avoids square fills`, false, "not measured"); continue; }
    const arcs = m.wp.ops.filter((o) => o.op === "arc").length;
    const imgs = m.wp.ops.filter((o) => o.op === "image").length;
    const rects = m.wp.ops.filter((o) => o.op === "fillRect").length;
    check(`${n} paints circles, not squares ` +
          `(${arcs} arcs, ${imgs} sprites, ${rects} rects)`,
          rects === 0 && (arcs > 0 || imgs > 0));
  }
}

console.log("\nthe glow presets don't rebuild a gradient per particle");
{
  // fireflies and sparks each built a fresh createRadialGradient() for
  // every particle on every frame — 336 and 205 per frame on a
  // 2560x1440 desktop, so ~10 000 throwaway gradient objects a second
  // at 30 fps. They now stamp a cached sprite instead. Both are the
  // densest presets by particle count, so a regression here is the
  // expensive kind.
  for (const n of ["fireflies", "sparks"]) {
    const m = measured[n];
    if (!m) { check(`${n} reuses its glow sprite`, false, "not measured"); continue; }
    const grads = m.wp.ops.filter(
      (o) => o.fillStyle && typeof o.fillStyle === "object"
             && Array.isArray(o.fillStyle.stops)).length;
    check(`${n} builds no per-particle gradients (${grads} found)`, grads === 0);
    const imgs = m.wp.ops.filter((o) => o.op === "image").length;
    check(`${n} stamps sprites instead (${imgs})`, imgs > 0);
  }
}

console.log("\nthe expensive glow follows the quality setting");
{
  // shadowBlur is the priciest property in Canvas 2D and its cost tracks
  // the radius: measured in Edge at 600 particles / 2560x1440, blur 12
  // costs 9.59 ms/frame against 1.85 ms with no blur at all. wormhole
  // applies it to every one of ~1840 draws per frame, and until v2.4.5
  // ignored the effect-quality setting entirely — "Performance" bought
  // the user nothing on the single most expensive preset.
  const wp = WP;
  check("wormhole's shadowBlur goes through _qualityBlur",
        /shadowBlur\s*=\s*_qualityBlur\(/.test(wp));
  check("_qualityBlur is defined", /function _qualityBlur\(/.test(wp));
  // Quality must keep today's appearance exactly; the other two tiers
  // are the ones allowed to trade glow for frame time.
  const m = wp.match(/function _qualityBlur\([\s\S]*?\n\}/);
  if (m) {
    const f = new Function("_qualityScale", m[0] + "; return _qualityBlur;");
    check("quality tier leaves the radius untouched", f(() => 1.0)(12) === 12);
    check("balanced tier shrinks it", f(() => 0.75)(12) === 9);
    check("performance tier shrinks it further", f(() => 0.5)(12) === 6);
  } else {
    check("_qualityBlur is readable", false);
  }
}

console.log("\nthe harness measures alpha rather than assuming it");
{
  // A guard on the guard. effectiveAlpha originally understood rgba()
  // only, so the hsla() that aurora and plasma paint in fell through to
  // the opaque default: every draw read as alpha 1.0 and the suite could
  // not have detected the bug it exists for. If someone narrows this
  // reader again, these fail rather than quietly passing everything.
  check("reads rgba()", Math.abs(effectiveAlpha({ op: "fill", fillStyle: "rgba(1,2,3,0.4)" }) - 0.4) < 1e-9);
  check("reads hsla()", Math.abs(effectiveAlpha({ op: "fill", fillStyle: "hsla(200, 85%, 62%, 0.3)" }) - 0.3) < 1e-9);
  check("reads #rrggbbaa", Math.abs(effectiveAlpha({ op: "fill", fillStyle: "#0080ff80" }) - 128 / 255) < 1e-6);
  check("multiplies globalAlpha in",
        Math.abs(effectiveAlpha({ op: "fill", globalAlpha: 0.5, fillStyle: "rgba(1,2,3,0.4)" }) - 0.2) < 1e-9);
  check("gradients report their strongest stop",
        Math.abs(effectiveAlpha({ op: "fill", fillStyle: { stops: [[0, "hsla(1,2%,3%,0.9)"], [1, "hsla(1,2%,3%,0)"]] } }) - 0.9) < 1e-9);
}

const total = results.passed + results.failed.length;
console.log(`\n  ${results.passed}/${total} passed`);
if (results.failed.length) {
  console.log("\n  failed:");
  for (const f of results.failed) console.log(`    - ${f}`);
}
process.exit(results.failed.length ? 1 : 0);
