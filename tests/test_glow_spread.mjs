// The glow "Spread" slider — labelling, and the claim that labelling makes.
//
// WHY THIS EXISTS
//
// The slider was called "Strength" / "Stärke" and the documentation said
// it multiplied "the glow's overall brightness/blur". The brightness half
// was never true. Every use of --glow scales a blur radius or a shadow
// spread; nothing reads it for opacity, brightness or colour.
//
// That mismatch cost a real debugging session. A preset saved at 50 %
// rendered visibly blocky while one saved at 100 % looked smooth, on the
// same monitor with the same background. The cause: --glow halves the
// 30 px grid blur to 15 px, and on a 128x36 grid stretched over a 16:9
// screen the cells are 20x40 px — so 15 px of blur no longer covers a
// cell vertically and the cell edges show as hard blocks. Nothing in the
// UI connected "Strength 50 %" to "visible grid".
//
// v2.4.4-beta.14 relabels it to Spread / Ausbreitung and adds a hint, with no
// behaviour change: stored preset slots and Quick Looks must render
// exactly as before.
//
// So the suite asserts two different kinds of thing:
//
//   1. The label and hint exist, in both languages, and are wired up.
//   2. The premise behind that label still holds — --glow is consumed
//      only by blur/shadow properties, and glowStrength still maps to it
//      1:1. If someone later makes --glow affect opacity, the wording
//      becomes wrong again and these tests are how that gets caught.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, "..");
const CONF = readFileSync(join(REPO, "wallpaper_bridge", "configurator.html"), "utf8");
const PAGE = readFileSync(join(REPO, "wallpaper_bridge", "wallpaper", "index.html"), "utf8");

let pass = 0, fail = 0;
function check(label, ok, detail) {
  if (ok) { pass++; console.error(`  ok    ${label}`); }
  else { fail++; console.error(`  FAIL  ${label}${detail ? "\n          " + detail : ""}`); }
}

console.error("\nGlow spread slider\n" + "=".repeat(68));

// --- 1. Labelling ---------------------------------------------------

// The old name is the bug. Assert it is gone from the translation table
// rather than from the file at large: "Strength" legitimately appears in
// other contexts (effect strength, etc.).
const strengthEntry = CONF.match(/"glow\.strength":\s*\{[^}]*\}/);
check("glow.strength translation entry exists", !!strengthEntry);
if (strengthEntry) {
  const e = strengthEntry[0];
  check("EN label no longer says 'Strength'", !/en:\s*"Strength"/.test(e), e);
  check("DE label no longer says 'Stärke'", !/de:\s*"Stärke"/.test(e), e);
  check("EN label is 'Spread'", /en:\s*"Spread"/.test(e), e);
  check("DE label is 'Ausbreitung'", /de:\s*"Ausbreitung"/.test(e), e);
}

// The hint must exist in both languages...
const hintEntry = CONF.match(/"glow\.spread_hint":\s*\{[\s\S]*?\n\s*\}/);
check("glow.spread_hint translation entry exists", !!hintEntry);
if (hintEntry) {
  const h = hintEntry[0];
  check("hint has an EN string", /en:\s*"[^"]{40,}"/.test(h));
  check("hint has a DE string", /de:\s*"[^"]{40,}"/.test(h));
  // The point of the hint is the causal link. If it does not mention the
  // grid blur it is decoration.
  check("EN hint names Grid blur as the thing being multiplied",
        /en:\s*"[^"]*[Gg]rid blur/.test(h));
  check("DE hint names the Raster-Weichzeichner",
        /de:\s*"[^"]*Raster-Weichzeichner/.test(h));
}

// ...and be rendered next to the slider, inside the same card.
const hintDiv = CONF.match(/<div class="hint"[^>]*data-i18n="glow\.spread_hint"[^>]*>/);
check("hint div is present in the markup", !!hintDiv);

// Wired to the translation pass: applyLang walks [data-i18n].
check("hint div carries data-i18n so it gets translated",
      !!hintDiv && /data-i18n=/.test(hintDiv[0]));

// The hint must sit near its slider, not in some unrelated card.
const sliderIdx = CONF.indexOf('id="glow-strength"');
const hintIdx = CONF.indexOf('data-i18n="glow.spread_hint"');
check("slider and hint both found", sliderIdx > 0 && hintIdx > 0);
check("hint follows the slider within the same card",
      sliderIdx > 0 && hintIdx > sliderIdx && (hintIdx - sliderIdx) < 1200,
      `slider@${sliderIdx} hint@${hintIdx} gap=${hintIdx - sliderIdx}`);

// --- 2. The premise the label rests on ------------------------------

// Every --glow consumer must be a blur radius or a shadow spread. This is
// the assertion that makes the new wording *true* rather than merely
// different, and the one that will fail if a future change makes the
// slider affect brightness after all.
const glowUses = [...PAGE.matchAll(/^.*var\(--glow[,)][^\n]*$/gm)].map(m => m[0].trim());
check("--glow is actually used by the wallpaper", glowUses.length > 0,
      `found ${glowUses.length}`);

const nonBlur = glowUses.filter(line => {
  // The declaration each use sits in. A use is legitimate if it lands in
  // a blur() call or a box-shadow/text-shadow length.
  if (/blur\(/.test(line)) return false;
  if (/^\s*(0|[\d.]+px|[\d.]+)\s/.test(line)) return false;   // shadow offset list
  if (/box-shadow|text-shadow|drop-shadow/.test(line)) return false;
  return true;
});
check("no --glow use affects brightness/opacity/colour", nonBlur.length === 0,
      nonBlur.length ? "suspicious:\n          " + nonBlur.join("\n          ") : "");

// Explicitly: --glow must not appear in an opacity or filter-brightness
// declaration. Named separately because the heuristic above could be
// loosened by accident; this one is unambiguous.
check("--glow never drives opacity",
      !/opacity[^;\n]*var\(--glow/.test(PAGE));
check("--glow never drives brightness()",
      !/brightness\([^)]*var\(--glow/.test(PAGE));

// --- 3. No behaviour change -----------------------------------------

// Stored slots keep the key glowStrength; only the label moved. If the
// key were renamed, every saved preset would silently lose its value.
check("the stored key is still glowStrength",
      /case\s*"glowStrength"/.test(PAGE),
      "renaming the key would orphan every saved preset slot");

// And the mapping must stay percent -> 1.0, unchanged.
const handler = PAGE.match(/case\s*"glowStrength":[\s\S]{0,240}?break;/);
check("glowStrength handler found", !!handler);
if (handler) {
  check("still maps percent to --glow by /100 with a 100 default",
        /setProperty\(\s*"--glow"/.test(handler[0]) &&
        /\|\|\s*100\s*\)\s*\/\s*100/.test(handler[0]),
        handler[0].replace(/\s+/g, " "));
}

// The slider range is part of "nothing changed" too: a stored 50 must
// still be reachable and mean the same thing.
check("slider range is unchanged (0-200, step 1)",
      /id="glow-strength"[^>]*min="0"[^>]*max="200"[^>]*step="1"/.test(CONF));

console.error("\n" + "=".repeat(68));
console.error(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
