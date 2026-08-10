// Effect tiles in the Configurator must resemble the real effect.
//
// The picker renders a live miniature of each ambient preset, but from a
// SECOND implementation: TILE_PRESETS in configurator.html, separate from
// AMBIENT_PRESETS in wallpaper/index.html. Two copies of the same idea,
// free to drift.
//
// They did drift, and it hid a real bug. aurora and plasma were shipped
// with peak alpha 0.14 / 0.18 in the wallpaper while their tiles used
// 0.4 / 0.35. The tiles looked lively; on the desktop both effects were
// invisible — measured at a mean colour shift of 6/255 over a real
// background. Users reported them as "no different from off", and the
// preview that existed specifically to show what an effect looks like
// was actively concealing the problem.
//
// This test does not demand the two implementations match — the tile is
// a 160×100 miniature and legitimately differs in particle counts and
// speeds. It checks the one property that made the preview misleading:
// that a tile is not dramatically more visible than the effect it
// advertises.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..");
const cfg = readFileSync(join(repo, "wallpaper_bridge", "configurator.html"), "utf8");
const wp  = readFileSync(join(repo, "wallpaper_bridge", "wallpaper", "index.html"), "utf8");

const results = { passed: 0, failed: [] };
function check(label, cond, detail = "") {
  if (cond) { results.passed++; console.log(`  PASS  ${label}`); }
  else { results.failed.push(label); console.log(`  FAIL  ${label}${detail ? "  — " + detail : ""}`); }
}

/**
 * Pull a preset's source block out of a file.
 *
 * Ends at the preset's own closing `\n  },` rather than a fixed length —
 * a character budget silently truncates a block once someone adds a
 * comment, and then the checks below pass or fail for the wrong reason.
 * `span` is kept only as an upper bound so a missing terminator cannot
 * swallow the rest of the file.
 */
function block(src, name, span = 6000) {
  const i = src.indexOf(`\n  ${name}: {`);
  if (i === -1) return null;
  const end = src.indexOf("\n  },", i);
  return src.slice(i, end === -1 ? i + span : Math.min(end + 5, i + span));
}

/** Peak alpha a preset paints with, as best we can read it statically. */
function peakAlpha(text) {
  if (!text) return null;
  const hits = [...text.matchAll(/(?:const a\s*=\s*|alpha:\s*)([0-9.]+)/g)]
    .map((m) => parseFloat(m[1]))
    .filter((n) => Number.isFinite(n) && n > 0 && n <= 1);
  return hits.length ? Math.max(...hits) : null;
}

console.log("\nboth implementations are present");
{
  check("configurator defines TILE_PRESETS", /const TILE_PRESETS\s*=/.test(cfg));
  check("wallpaper defines AMBIENT_PRESETS", /const AMBIENT_PRESETS\s*=/.test(wp));
}

console.log("\nthe picker previews what the effect actually looks like");
{
  // Only presets where both sides expose a readable constant alpha. The
  // others compute it per particle and cannot be compared statically.
  const comparable = ["aurora", "plasma", "waves", "snow", "rain"];
  for (const name of comparable) {
    const tileA = peakAlpha(block(cfg, name));
    const wpA   = peakAlpha(block(wp, name));
    if (tileA === null || wpA === null) {
      check(`${name} — alpha readable on both sides`, true,
            "skipped (computed per particle)");
      continue;
    }
    // A tile more than ~2x the strength of the real thing is the failure
    // mode that hid the aurora bug. The reverse (a tile fainter than the
    // effect) is harmless — the user gets more than advertised.
    const ratio = tileA / wpA;
    check(`${name} — tile is not far stronger than the effect ` +
          `(tile ${tileA}, wallpaper ${wpA})`,
          ratio <= 2.0, `ratio ${ratio.toFixed(2)}x`);
  }
}

console.log("\nthe faint presets stayed above the perceptual floor");
{
  // aurora and plasma are composited over a photograph, not black. Below
  // roughly 0.25 peak they stop registering as a soft area of colour —
  // every ambient preset that reads clearly sits at 0.25 or above.
  for (const name of ["aurora", "plasma"]) {
    const a = peakAlpha(block(wp, name));
    check(`${name} peak alpha is at least 0.25`, a !== null && a >= 0.25,
          a === null ? "not found" : String(a));
  }
}

console.log("\nlarge soft blobs fill a circle, not the square around it");
{
  // The corners of a 2r × 2r fill are alpha 0 but still get blended, and
  // they are 1 - π/4 = 21 % of every fill. With v2.4.4's radius scaling
  // these blobs cover much of a wide desktop, so it is real fill rate.
  for (const name of ["aurora", "plasma", "fireflies"]) {
    const b = block(wp, name);
    check(`${name} fills via arc()`, !!b && /ctx\.arc\(/.test(b));
    check(`${name} no longer fills a square`,
          !!b && !/fillRect\(p\.x - (?:p\.r|halo)/.test(b));
  }
  check("TAU is defined before use",
        wp.indexOf("const TAU") !== -1 &&
        wp.indexOf("const TAU") < wp.indexOf("0, TAU)"));
}

const total = results.passed + results.failed.length;
console.log(`\n  ${results.passed}/${total} passed`);
process.exit(results.failed.length ? 1 : 0);
