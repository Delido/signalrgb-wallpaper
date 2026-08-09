// rgbToRgba() — the tint helper every tinted effect goes through.
//
// It was a two-step string replace that only recognised "rgb(R,G,B)".
// currentTintCss starts life as the hex literal "#6ab0ff" and only
// becomes an rgb() string once the first glow frame arrives from the
// bridge. Before that, rgbToRgba() found no "rgb(" to replace and
// returned the hex unchanged — so every colour stop in a gradient came
// back identical and fully opaque.
//
// Visible result: hover-glow rendered as a flat blue disc instead of a
// soft glow. It was blamed on Wallpaper Engine's browser and carried a
// "Lively only" badge for it, but the host was never the variable — the
// timing was. Anywhere the bridge is slow to connect, restarting, or not
// running, the hex default is still in place and the same flat disc
// appears on any host.
//
// 25 call sites share this helper, so the failure is not limited to
// hover-glow: every tinted ambient effect degrades the same way.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..");
const INDEX = join(repo, "wallpaper_bridge", "wallpaper", "index.html");
const src = readFileSync(INDEX, "utf8");

const results = { passed: 0, failed: [] };
function check(label, cond, detail = "") {
  if (cond) { results.passed++; console.log(`  PASS  ${label}`); }
  else { results.failed.push(label); console.log(`  FAIL  ${label}${detail ? "  — " + detail : ""}`); }
}

// Pull the real implementation out of index.html and run it, rather than
// re-typing it here — a copy would keep passing after the original broke.
function loadHelper() {
  const m = src.match(/function rgbToRgba\(rgb, a\) \{[\s\S]*?\n\}/);
  if (!m) return null;
  // eslint-disable-next-line no-new-func
  return new Function(`${m[0]}; return rgbToRgba;`)();
}

console.log("\nrgbToRgba is present and extractable");
const rgbToRgba = loadHelper();
check("found rgbToRgba in index.html", typeof rgbToRgba === "function");
if (typeof rgbToRgba !== "function") {
  console.log(`\n  ${results.passed}/${results.passed + results.failed.length} passed`);
  process.exit(1);
}

function alphaOf(css) {
  const m = String(css).match(/rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*([\d.]+)\s*\)/);
  return m ? parseFloat(m[1]) : null;
}

console.log("\nrgb() input — the path that always worked");
{
  const out = rgbToRgba("rgb(106,176,255)", 0.35);
  check("returns an rgba() string", /^rgba\(/.test(out), out);
  check("carries the requested alpha", alphaOf(out) === 0.35, out);
}

console.log("\nhex input — the default tint before any glow frame arrives");
{
  const a = rgbToRgba("#6ab0ff", 0.35);
  const b = rgbToRgba("#6ab0ff", 0.10);
  const c = rgbToRgba("#6ab0ff", 0);
  check("hex is converted to rgba()", /^rgba\(/.test(a), a);
  check("alpha 0.35 survives", alphaOf(a) === 0.35, a);
  check("alpha 0.10 survives", alphaOf(b) === 0.1, b);
  check("alpha 0 survives", alphaOf(c) === 0, c);
  // The actual bug: a gradient needs its stops to differ. If all three
  // come back identical there is no ramp, just a solid fill.
  check("the three gradient stops are not identical",
        !(a === b && b === c), `all three = ${a}`);
  check("the outer stop is transparent", alphaOf(c) === 0, c);
  // Channel values must be preserved, not just the format.
  check("hex channels decoded correctly (#6ab0ff → 106,176,255)",
        /rgba\(\s*106\s*,\s*176\s*,\s*255/.test(a), a);
}

console.log("\nshort hex and uppercase");
{
  const s = rgbToRgba("#0af", 0.5);
  check("#0af expands to 0,170,255", /rgba\(\s*0\s*,\s*170\s*,\s*255/.test(s), s);
  const u = rgbToRgba("#6AB0FF", 0.5);
  check("uppercase hex works", /rgba\(\s*106\s*,\s*176\s*,\s*255/.test(u), u);
}

console.log("\nrgba() input is not double-wrapped");
{
  const out = rgbToRgba("rgba(10,20,30,0.9)", 0.25);
  check("stays a single rgba()", (out.match(/rgba\(/g) || []).length === 1, out);
  check("alpha is replaced, not appended", alphaOf(out) === 0.25, out);
}

console.log("\nthe default tint literal still matches what the helper expects");
{
  const m = src.match(/let\s+currentTintCss\s*=\s*"([^"]+)"/);
  check("found the currentTintCss default", !!m, m ? m[1] : "not found");
  if (m) {
    const out = rgbToRgba(m[1], 0.4);
    check(`default ${m[1]} converts to rgba()`, /^rgba\(/.test(out), out);
    check("default tint yields the requested alpha", alphaOf(out) === 0.4, out);
  }
}

const total = results.passed + results.failed.length;
console.log(`\n  ${results.passed}/${total} passed`);
process.exit(results.failed.length ? 1 : 0);
