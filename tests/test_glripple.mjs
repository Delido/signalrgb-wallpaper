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
import vm from "node:vm";

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

console.log("\nboth SVG filters are primed before they can be applied");
{
  // A displacement filter attached to #bg with an feImage that has no
  // href yet gets an EMPTY in2. feDisplacementMap then shreds the
  // source instead of bending it: the background reads dark and
  // wrongly coloured until something sets a real href, at which point
  // it visibly jumps.
  //
  // That is what Liquid Distortion did. ensureFilter() built the
  // filter, attached it, and left the href unset until the first
  // mouse move. Reported as "the image is dark and changes to a
  // completely different colour when I move the mouse" — and toggling
  // the effect off and on appeared to fix it, because by the second
  // enable() the map already had content.
  //
  // The water module never had the bug: it primes the href on the
  // same line it builds the filter, and starts at scale=0 so even an
  // in-flight href load cannot displace anything. Both modules now
  // carry both guarantees, and this checks them as a pair so the next
  // displacement effect cannot be added with only one.
  const modules = [
    { name: "Liquid Distortion", id: "fx-ripple" },
    { name: "water",             id: "pixelfx-water" },
  ];
  for (const m of modules) {
    // The filter is built inside ensureFilter(); slice that function
    // out rather than searching the whole file, or a match from the
    // OTHER module would satisfy the check.
    const at = src.indexOf(`id="${m.id}-filter"`);
    const scope = at === -1 ? "" : src.slice(Math.max(0, at - 600), at + 1600);
    check(`${m.name}: filter is defined`, at !== -1);
    check(`${m.name}: starts at scale="0", not a live amplitude`,
          /scale="0"/.test(scope), scope.match(/scale="[^"]*"/)?.[0] || "none");
    check(`${m.name}: href is primed where the filter is built`,
          /setAttribute\("href", mapCanvas\.toDataURL\(\)\)/.test(scope));
  }

  // Raising the amplitude is only correct once a map exists — and it
  // has to happen, or the effect stays invisible at scale 0 forever.
  check("Liquid Distortion lifts scale off 0 once the map is painted",
        /feDisp\.setAttribute\("scale", String\(GL_SCALE\)\)/.test(src));
  // The filter node outlives disable(), so a stale amplitude would
  // apply the previous session's map for a frame on re-enable.
  check("disable() drops the amplitude back to 0",
        /feDisp\.setAttribute\("scale", "0"\)/.test(src));
}

// --- texture-upload diagnostics ---------------------------------------
// no_img said "no texture" and nothing more, which is where a real
// investigation stalled: one screen sat on the SVG path with no_img
// climbing past 1300 while WebGL was available (no_gl=0) and the bridge
// served the image with the right CORS header. Three different failures
// produce that same counter and need different fixes, so the loader
// counts them apart. Run it rather than grep for it — the interesting
// part is which counter moves.
{
  const body = (src.match(/function _glRippleLoadTexture\(src, w, h\)[\s\S]*?\n\}/) || [])[0];
  check("the texture loader was extracted", !!body);

  if (body) {
    const drive = (mode) => {
      const _diag = { texOk: 0, texErr: 0, texNotReady: 0, texThrew: 0, texBytes: 0 };
      const made = [];
      const ctx = {
        _diag, Math,
        console: { warn() {}, error() {} },
        glRipple: {
          setImage() {
            if (mode === "throw") throw new Error("texImage2D failed");
            return mode === "ok";
          },
          clearImage() {},
        },
        Image: function () {
          const o = { set src(_v) { made.push(o); },
                      naturalWidth: 2560, naturalHeight: 1440 };
          return o;
        },
      };
      vm.runInNewContext(body + "\n_glRippleLoadTexture('x.png', 2560, 1440);",
                         ctx, { timeout: 4000 });
      const img = made[0];
      if (mode === "err") img.onerror(); else img.onload();
      return _diag;
    };

    const only = (d, key) =>
      d[key] === 1 && Object.entries(d)
        .filter(([k]) => k !== key && k !== "texBytes")
        .every(([, v]) => v === 0);

    check("a successful upload counts as texOk", only(drive("ok"), "texOk"));
    check("a not-ready GL context counts separately",
          only(drive("notready"), "texNotReady"),
          "this is the case that used to look like a CORS refusal");
    check("a throwing texImage2D counts separately", only(drive("throw"), "texThrew"));
    check("an image load error counts separately", only(drive("err"), "texErr"));
    check("the image scale is recorded", drive("ok").texBytes > 0);
  }

  // The wrapper has to report the outcome, or texNotReady would fire on
  // every successful upload — setImage() returned undefined before.
  check("the glRipple wrapper returns whether the upload took",
        /hasImage = renderer\.setImage\(img, w, h\);[\s\S]{0,140}?return hasImage;/.test(src),
        "an undefined return makes the counter meaningless");
  check("the wrapper returns false when WebGL is unavailable",
        /if \(!probe\(\)\) return false;/.test(src));
}

// --- premultiplied alpha ----------------------------------------------
// The overlay drew half-transparent pixels twice as bright, for as long
// as water ripple or Liquid Distortion was animating. Reported as
// "wasserwelle fuehrt nun auf 2ten Monitor wieder dazu das es heller
// ist ... waehrend der animation", eventually on both screens.
//
// The cause was a mismatched trio: the shader emitted straight colour,
// blendFunc(SRC_ALPHA, ONE_MINUS_SRC_ALPHA) multiplied alpha by itself,
// and the context declared premultipliedAlpha:false so the browser
// divided colour by alpha again when compositing. Net effect at alpha a:
// (rgb*a)/(a*a) = rgb/a. At a=1 that is exactly 1, which is why an
// opaque background never showed it.
//
// The three settings are one decision. Rather than assert on each in
// isolation, model the pipeline and check what reaches the screen.
{
  const shader = (src2) => {
    const straight = /gl_FragColor = vec4\(c\.rgb, c\.a \* uAlpha\)/.test(src2);
    const premul = /gl_FragColor = vec4\(c\.rgb \* a, a\)/.test(src2);
    return straight ? "straight" : (premul ? "premultiplied" : "unknown");
  };
  const blendSrcFactor = (src2) =>
    /blendFuncSeparate\(gl\.ONE, gl\.ONE_MINUS_SRC_ALPHA/.test(src2) ? 1
      : (/blendFunc\(gl\.SRC_ALPHA, gl\.ONE_MINUS_SRC_ALPHA\)/.test(src2) ? "a" : "?");
  // Match the option inside the opts object literal, not the word
  // anywhere in the file: the comment above it explains both settings
  // and contains "premultipliedAlpha:true" as prose, which made this
  // check pass against code that said false.
  const ctxPremul = (src2) =>
    /var opts = \{[^}]*premultipliedAlpha:\s*true/.test(src2);

  check("the shader emits premultiplied colour",
        shader(mod) === "premultiplied", shader(mod));
  check("the colour blend factor is ONE, not SRC_ALPHA",
        blendSrcFactor(mod) === 1,
        "SRC_ALPHA on premultiplied colour multiplies alpha in twice");
  check("the context declares premultipliedAlpha: true", ctxPremul(mod),
        "false makes the browser divide colour by alpha again");

  // What actually reaches the screen for a half-transparent pixel.
  const onScreen = () => {
    const a = 0.5, rgb = 0.8;
    const srcRgb = shader(mod) === "premultiplied" ? rgb * a : rgb;
    const factor = blendSrcFactor(mod) === 1 ? 1 : a;
    const fbRgb = srcRgb * factor;
    const fbA = a * factor;
    // premultipliedAlpha:false means the browser un-premultiplies.
    return ctxPremul(mod) ? fbRgb : (fbA ? fbRgb / fbA : 0);
  };
  const want = 0.8 * 0.5;   // rgb * a, composited over black
  check("a half-transparent pixel composites at its true brightness",
        Math.abs(onScreen() - want) < 1e-9,
        `on screen ${onScreen().toFixed(3)}, expected ${want.toFixed(3)}`);

  // Opaque pixels must be untouched — this is the case that always
  // worked and must keep working.
  const opaque = () => {
    const a = 1, rgb = 0.8;
    const srcRgb = shader(mod) === "premultiplied" ? rgb * a : rgb;
    const factor = blendSrcFactor(mod) === 1 ? 1 : a;
    const fbRgb = srcRgb * factor, fbA = a * factor;
    return ctxPremul(mod) ? fbRgb : (fbA ? fbRgb / fbA : 0);
  };
  check("an opaque pixel is unchanged", Math.abs(opaque() - 0.8) < 1e-9,
        `${opaque()}`);
}

const total = results.passed + results.failed.length;
console.log(`\n  ${results.passed}/${total} passed`);
process.exit(results.failed.length ? 1 : 0);
