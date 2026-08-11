// glRipple — the WebGL displacement path for water-ripple and Liquid
// Distortion, and its wiring into the wallpaper page.
//
// Background: those two effects drew through an SVG filter whose
// <feImage> step produces nothing at all in Wallpaper Engine's bundled
// CEF (measured: 100 % transparent output, while feFlood renders and
// feDisplacementMap at scale=0 returns the source untouched). The shader
// path replaces it. Measured in WE: ANGLE/Direct3D11 on the real GPU,
// 0.36 ms/frame, and all six background-fit modes within 0-3 % of a
// Canvas2D reference — the same figures as Chromium 151.
//
// Two properties matter most and are easy to regress:
//   * the overlay must never be left covering the wallpaper when no
//     effect is drawing, and
//   * the SVG fallback must stay intact for hosts without WebGL.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { execFileSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..");
const WP = join(repo, "wallpaper_bridge", "wallpaper");
const src = readFileSync(join(WP, "index.html"), "utf8");
const mod = readFileSync(join(WP, "glripple.js"), "utf8");

const results = { passed: 0, failed: [] };
function check(label, cond, detail = "") {
  if (cond) { results.passed++; console.log(`  PASS  ${label}`); }
  else { results.failed.push(label); console.log(`  FAIL  ${label}${detail ? "  — " + detail : ""}`); }
}

console.log("\nmodule ships with the bundle");
{
  // `require` is not available in an ES module — check the file where it
  // actually lives instead of copying it to a temp path first.
  check("glripple.js parses", (() => {
    try {
      execFileSync(process.execPath, ["--check", join(WP, "glripple.js")],
                   { stdio: "pipe" });
      return true;
    } catch { return false; }
  })());
  check("index.html loads it", /<script src="glripple\.js"><\/script>/.test(src));
  check("exports window.GLRipple", /global\.GLRipple\s*=\s*GLRipple/.test(mod));
  check("exports computeUV for tests", /GLRipple\.computeUV\s*=\s*computeUV/.test(mod));
}

console.log("\noverlay markup and styling");
{
  check("canvas exists", /<canvas id="glripple-canvas">/.test(src));
  check("hidden until activated", /#glripple-canvas\s*\{[^}]*display:\s*none/.test(src));
  check("shown via .on", /#glripple-canvas\.on\s*\{\s*display:\s*block/.test(src));
  // visibility, not display: #bg must keep its computed geometry so the
  // CSS background-size / position stay resolvable while hidden.
  check("#bg hidden with visibility, not display",
        /body\.glripple-active #bg\s*\{\s*visibility:\s*hidden/.test(src));
  check("overlay does not eat input", /#glripple-canvas\s*\{[^}]*pointer-events:\s*none/.test(src));
}

console.log("\nfit modes are computed, not reimplemented in CSS");
{
  for (const fit of ["cover", "contain", "fill", "tile", "tile-x", "tile-y"]) {
    check(`computeUV handles '${fit}'`, new RegExp(`case "${fit}"`).test(mod));
  }
  // contain letterboxes, so it samples PAST the image edge (scale > 1).
  // cover crops, so it samples a subset (scale < 1). Inverting these was
  // a real bug during development.
  const containBlock = mod.slice(mod.indexOf('case "contain"'), mod.indexOf('case "tile"'));
  check("contain samples beyond the image (imgAR/viewAR, not its inverse)",
        /sy\s*=\s*imgAR\s*\/\s*viewAR/.test(containBlock) &&
        /sx\s*=\s*viewAR\s*\/\s*imgAR/.test(containBlock), containBlock.trim());
}

console.log("\nSVG fallback is preserved");
{
  check("filter construction still present", /feDisplacementMap/.test(src));
  check("water still has an SVG path", /pixelfx-water-filter/.test(src));
  check("mousefx ripple still has an SVG path", /fx-ripple-filter/.test(src));
  // Both modules must consult usable() before deciding which path to
  // take — otherwise a host without WebGL gets no effect at all.
  const usableCalls = (src.match(/glRipple\.usable\(\)/g) || []).length;
  check("usable() gates both modules (>=4 call sites)", usableCalls >= 4,
        `found ${usableCalls}`);
}

console.log("\noverlay is released when nothing is drawing");
{
  const stops = (src.match(/glRipple\.stop\(/g) || []).length;
  check("stop() called from both modules (>=4 sites)", stops >= 4, `found ${stops}`);
  check("water releases on idle", /glRipple\.stop\("water"\)/.test(src));
  check("mousefx releases on idle", /glRipple\.stop\("mousefx"\)/.test(src));
  // A shared overlay with two possible writers needs arbitration, or the
  // second one each frame wins and the first flickers.
  check("draw() takes an owner id", /draw\(who,\s*mapCanvas,\s*amp\)/.test(src));
  check("draw() refuses a non-owner", /owner\s*&&\s*owner\s*!==\s*who/.test(src));
  check("stop() refuses a non-owner", /owner\s*&&\s*who\s*&&\s*owner\s*!==\s*who/.test(src));
}

console.log("\nbackground state is mirrored, not reimplemented");
{
  check("texture loaded from the image path", /_glRippleLoadTexture\(/.test(src));
  check("texture request is CORS-clean", /crossOrigin\s*=\s*"anonymous"/.test(src));
  check("video backgrounds clear the texture",
        /_setVideoBg[\s\S]{0,400}?glRipple\.clearImage\(\)/.test(src));
  check("fit changes propagate", /applyBgFit[\s\S]{0,200}?glRipple\.syncFit\(\)/.test(src));
  check("tile-scale changes propagate",
        /applyBgTileScale[\s\S]{0,300}?glRipple\.syncFit\(\)/.test(src));
  // parallax writes a transform on #bg; the overlay has to follow it
  // rather than the shader duplicating the maths.
  check("parallax transform is mirrored onto the canvas",
        /canvas\.style\.transform\s*=\s*t/.test(src));
}

console.log("\ncontext loss is handled");
{
  check("renderer exposes onContextLost", /onContextLost\s*=\s*function/.test(mod));
  // v2.4.10: a lost context used to kill water + liquid distortion for
  // good. _build() nulls _imgTex on restore, but nothing re-uploaded the
  // background — and `hasImage` stayed true, so usable() kept claiming
  // the WebGL path was fine and the effects never fell back to SVG.
  // Reported as "water and mouse distortion went completely dead on one
  // screen while canvas and widgets kept running".
  //
  // Matched without a character budget: the handler carries a long
  // comment, and a `[\s\S]{0,200}` window silently stops matching the
  // moment someone adds a line to it.
  const lostBody = (() => {
    const at = src.indexOf("onContextLost(() => {");
    if (at === -1) return "";
    let i = src.indexOf("{", at + 18), depth = 0;
    for (; i < src.length; i++) {
      if (src[i] === "{") depth++;
      else if (src[i] === "}" && --depth === 0) return src.slice(at, i + 1);
    }
    return "";
  // Kommentare entfernen: ein auskommentiertes Statement darf die
  // Pruefung nicht erfuellen.
  })().replace(/\/\/[^\n]*/g, "");

  check("bridge hides the overlay on loss", /hide\(\)/.test(lostBody));
  check("bridge drops hasImage so usable() falls back to SVG",
        /hasImage\s*=\s*false/.test(lostBody));
  check("renderer exposes onContextRestored",
        /onContextRestored\s*=\s*function/.test(mod));
  check("restore re-uploads the texture",
        /onContextRestored\(\(\)\s*=>/.test(src) &&
        /_glRippleLoadTexture\(_glRippleLastSrc/.test(src));
  check("the last texture source is remembered",
        /let _glRippleLastSrc/.test(src) &&
        /_glRippleLastSrc\s*=\s*src/.test(src));
  check("webglcontextrestored rebuilds", /webglcontextrestored/.test(mod));
}

console.log("\ncomputeUV behaviour (run against the real module)");
{
  // Execute the module in this process and exercise the exported maths.
  // The IIFE closes over `window`, so supply that name rather than
  // renaming its parameter.
  const fakeWindow = {};
  // eslint-disable-next-line no-new-func
  new Function("window", mod)(fakeWindow);
  const computeUV = fakeWindow.GLRipple && fakeWindow.GLRipple.computeUV;
  check("computeUV is callable", typeof computeUV === "function");
  if (typeof computeUV === "function") {
    // viewport 150x84 (AR 1.786), image 300x200 (AR 1.5)
    const cover = computeUV("cover", 100, 150, 84, 300, 200);
    check("cover crops on Y (scale < 1)", cover.scale[1] < 1 && Math.abs(cover.scale[0] - 1) < 1e-6,
          JSON.stringify(cover.scale));
    const contain = computeUV("contain", 100, 150, 84, 300, 200);
    check("contain letterboxes on X (scale > 1)", contain.scale[0] > 1,
          JSON.stringify(contain.scale));
    const fill = computeUV("fill", 100, 150, 84, 300, 200);
    check("fill stretches to exactly 1:1",
          Math.abs(fill.scale[0] - 1) < 1e-6 && Math.abs(fill.scale[1] - 1) < 1e-6,
          JSON.stringify(fill.scale));
    const tile = computeUV("tile", 25, 150, 84, 300, 200);
    check("tile sets repeat", tile.repeat === 1);
    check("tile scale reflects the percentage",
          Math.abs(tile.scale[0] - 150 / (300 * 0.25)) < 1e-6,
          JSON.stringify(tile.scale));
    // Centre of the viewport must map to the centre of a tile, so the
    // grid is centred the way CSS background-position: center does it.
    check("tile offset centres a tile",
          Math.abs((0.5 * tile.scale[0] + tile.offset[0]) % 1 - 0.5) < 1e-6,
          JSON.stringify(tile.offset));
    // Degenerate inputs must not produce NaN uniforms.
    const zero = computeUV("cover", 100, 0, 0, 0, 0);
    check("zero-sized input yields a safe identity",
          zero.scale[0] === 1 && zero.scale[1] === 1 && zero.repeat === 0,
          JSON.stringify(zero));
  }
}

const total = results.passed + results.failed.length;
console.log(`\n  ${results.passed}/${total} passed`);
process.exit(results.failed.length ? 1 : 0);
