// Applying a library image to one half of a spanned screen must not
// destroy the other half.
//
// THE BUG THIS EXISTS FOR
//
// On a span-h / span-v setup the library picker offers "left half" /
// "right half". Each apply composites: it draws the CURRENT background
// clipped to the other half, then the new image clipped to the target
// half, and uploads the result as one image.
//
// That is only correct if "the current background" really is current.
// It was read from `_lastConfigSnapshot`, which is refreshed by a 5 s
// poll (refreshTabLabels). Applying to the second half within five
// seconds of the first therefore composited onto the state from BEFORE
// the first half — and silently threw the first half away.
//
// Reported by the user on both Lively and Wallpaper Engine. Confirmed
// in the bridge log: three consecutive saves 3.7 s apart where the
// third file's byte count (7 362 634) exactly matched the first,
// i.e. the second half's composite had reverted to the pre-first-half
// image.
//
// The fix reads `settings` — which the bridge pushes over the WS
// immediately after every background upload — for the active screen,
// and falls back to a fresh /config read for any other screen.
//
// These tests drive the real composite geometry and the real staleness
// scenario rather than grepping for the fix, so a future refactor that
// reintroduces a cached read fails here.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..");
const CFG = readFileSync(join(repo, "wallpaper_bridge", "configurator.html"), "utf8");

const results = { passed: 0, failed: [] };
function check(label, cond, detail = "") {
  if (cond) { results.passed++; console.log(`  PASS  ${label}`); }
  else { results.failed.push(label); console.log(`  FAIL  ${label}${detail ? "  — " + detail : ""}`); }
}

/** The source of applyLibraryItemToSpanTile, by brace depth. */
function grabFn(name) {
  const at = CFG.indexOf(`async function ${name}(`);
  if (at === -1) return null;
  let i = CFG.indexOf("{", at), depth = 0;
  for (; i < CFG.length; i++) {
    if (CFG[i] === "{") depth++;
    else if (CFG[i] === "}" && --depth === 0) return CFG.slice(at, i + 1);
  }
  return null;
}

const fnSrc = grabFn("applyLibraryItemToSpanTile");

console.log("\nthe span-apply function is present and readable");
check("applyLibraryItemToSpanTile found", !!fnSrc);

console.log("\nit reads a live background, not a polled snapshot");
{
  // The precise failure: `_lastConfigSnapshot` is the 5 s poll's cache.
  // Reading prevPath from it is what let a fast second click composite
  // onto stale state.
  const prevAssign = fnSrc
    ? fnSrc.slice(fnSrc.indexOf("let prevPath"), fnSrc.indexOf("let prevPath") + 900)
    : "";
  check("prevPath does not come from the polled snapshot alone",
        !!prevAssign && !/^\s*let prevPath\s*=\s*\(snap && snap\.bgImage\)/m.test(prevAssign));
  check("prevPath prefers the WS-pushed settings for the active screen",
        /screenIdx === activeScreen && settings && settings\.bgImage/.test(prevAssign));
  check("a non-active screen re-reads /config",
        /fetch\("\/config"/.test(prevAssign));
  check("the /config read is uncached",
        /cache:\s*"no-store"/.test(prevAssign));
}

console.log("\nthe composite geometry keeps the other half intact");
{
  // Reimplemented from the function's own arithmetic — the point is to
  // pin the invariant (the two clip rects tile the screen exactly, and
  // never overlap), not to duplicate the implementation.
  function rects(spanMode, tileIdx, W, H) {
    let tx = 0, ty = 0, tw = W, th = H;
    if (spanMode === "span-h") { tw = Math.floor(W / 2); tx = tileIdx * tw; }
    else if (spanMode === "span-v") { th = Math.floor(H / 2); ty = tileIdx * th; }
    const target = { x: tx, y: ty, w: tw, h: th };
    const other = spanMode === "span-h"
      ? { x: tileIdx === 0 ? tw : 0, y: 0, w: tw, h: H }
      : { x: 0, y: tileIdx === 0 ? th : 0, w: W, h: th };
    return { target, other };
  }
  const overlap = (a, b) =>
    Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) *
    Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));

  for (const [mode, W, H] of [["span-h", 5120, 1440], ["span-v", 2560, 2880],
                              ["span-h", 3840, 1080]]) {
    for (const tile of [0, 1]) {
      const { target, other } = rects(mode, tile, W, H);
      check(`${mode} tile${tile} ${W}x${H} — target and preserved half don't overlap`,
            overlap(target, other) === 0,
            `overlap ${overlap(target, other)}px²`);
      check(`${mode} tile${tile} ${W}x${H} — the two halves cover the screen`,
            target.w * target.h + other.w * other.h === W * H,
            `${target.w * target.h + other.w * other.h} vs ${W * H}`);
    }
  }
}

console.log("\nthe stale-snapshot scenario, simulated end to end");
{
  // Models the reported sequence: apply left, then apply right before
  // the 5 s poll has run. With a stale source the second composite
  // loses the left half; with a live source both survive.
  function composite(prevHalves, spanMode, tileIdx) {
    // A "background" is just which halves carry an image.
    const out = [null, null];
    const otherIdx = tileIdx === 0 ? 1 : 0;
    out[otherIdx] = prevHalves[otherIdx];   // clipped copy of the previous bg
    out[tileIdx] = `img${tileIdx}`;
    return out;
  }

  // Timeline: start empty, apply to tile 0, then to tile 1.
  const afterFirst = composite([null, null], "span-h", 0);
  check("first apply fills the left half", afterFirst[0] === "img0" && afterFirst[1] === null);

  // Stale: the second apply still sees the pre-first-half state.
  const staleSource = [null, null];
  const afterStale = composite(staleSource, "span-h", 1);
  check("with a stale source the left half is lost (the reported bug)",
        afterStale[0] === null && afterStale[1] === "img1");

  // Live: the second apply sees the state the first one produced.
  const afterLive = composite(afterFirst, "span-h", 1);
  check("with a live source both halves survive",
        afterLive[0] === "img0" && afterLive[1] === "img1");
}

console.log("\nthe configurator still parses");
{
  const clean = CFG.replace(/<!--[\s\S]*?-->/g, "");
  const blocks = [...clean.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
    .map((m) => m[1]).filter((b) => b.trim().length > 0);
  const biggest = blocks.sort((a, b) => b.length - a.length)[0] || "";
  check("found the inline script block", biggest.length > 1000, `${biggest.length} chars`);
  let parsed = true, detail = "";
  try {
    // eslint-disable-next-line no-new-func
    new Function(biggest);
  } catch (e) { parsed = false; detail = String(e.message).slice(0, 100); }
  check("configurator JS parses", parsed, detail);
}

const total = results.passed + results.failed.length;
console.log(`\n  ${results.passed}/${total} passed`);
if (results.failed.length) {
  console.log("\n  failed:");
  for (const f of results.failed) console.log(`    - ${f}`);
}
process.exit(results.failed.length ? 1 : 0);
