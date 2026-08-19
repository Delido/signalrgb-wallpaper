// The first-run wizard's decision logic.
//
// WHY THIS EXISTS
//
// The tour explains where controls are. It has always done that
// competently, and it never stopped "my wallpaper is black and I do not
// know why" from being the most common report — because an explained
// blank screen is still a blank screen. The wizard answers a different
// question: it leaves the user with a finished wallpaper.
//
// That makes its gating logic the part worth testing. Show it to the
// wrong person and it is an obstacle:
//
//   * a returning user who already saw the tour must NOT get it
//   * anyone who finished or skipped it must not see it again
//   * skipping it must suppress the tour as well — someone who
//     dismissed one intro does not want the other one next
//
// None of that is visible in a screenshot, and all of it is one
// inverted condition away from being wrong. The suite extracts the real
// functions and runs them against a fake localStorage rather than
// re-describing the rules here.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const HERE = dirname(fileURLToPath(import.meta.url));
const HTML = readFileSync(
  join(HERE, "..", "wallpaper_bridge", "configurator.html"), "utf8");

let pass = 0, fail = 0;
function check(label, ok, detail) {
  if (ok) { pass++; console.error(`  ok    ${label}`); }
  else { fail++; console.error(`  FAIL  ${label}${detail ? "\n          " + detail : ""}`); }
}

console.error("\nFirst-run wizard\n" + "=".repeat(68));

const noComments = HTML.replace(/<!--[\s\S]*?-->/g, "");
const src = [...noComments.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).sort((a, b) => b.length - a.length)[0];

const TOUR_KEY = (src.match(/const TOUR_KEY\s*=\s*"([^"]+)"/) || [])[1];
const WIZ_KEY = (src.match(/const WIZ_KEY\s*=\s*"([^"]+)"/) || [])[1];

// --- the pieces must exist at all --------------------------------------
check("WIZ_KEY is declared", !!WIZ_KEY, String(WIZ_KEY));
check("TOUR_KEY is declared", !!TOUR_KEY, String(TOUR_KEY));
check("the two keys are distinct", WIZ_KEY !== TOUR_KEY);
check("maybeShowWizard is defined", /function maybeShowWizard\s*\(/.test(src));
check("closeWizard is defined", /function closeWizard\s*\(/.test(src));
check("wizard runs before the tour",
      /if \(maybeShowWizard\(\)\) return;[\s\S]{0,120}maybeShowTour\(\)/.test(src),
      "_tryFirstRunTour must give the wizard precedence");

// The wizard applies a Look for real rather than just recording a pick —
// that is the whole difference from the tour.
check("picking a Look applies the bundle",
      /applyLookBundle\(bundle,\s*true\)/.test(src),
      "must call applyLookBundle with skipConfirm");
check("applyLookBundle accepts skipConfirm",
      /function applyLookBundle\(bundle,\s*skipConfirm\)/.test(src));
check("the confirm() is conditional on it",
      /if \(!skipConfirm && !confirm\(msg\)\)/.test(src));

// Step 2 reads the real library variable. An invented name would be
// swallowed by the Array.isArray guard and leave the step permanently
// empty — which is exactly what happened while writing this.
// Whatever the step reads must actually be declared somewhere. An
// invented name is swallowed by the Array.isArray guard and leaves the
// step permanently empty with no error — which is exactly what happened
// while writing this (_libraryItems does not exist).
const bgRead = src.match(/const items = \(Array\.isArray\((\w+)\)/);
check("background step reads some catalogue variable", !!bgRead,
      bgRead ? bgRead[1] : "no Array.isArray read found in the bg step");
if (bgRead) {
  const name = bgRead[1];
  const declared = new RegExp(
    `(?:let|const|var)\\s+${name}\\b|\\b${name}\\s*=\\s*Array\\.isArray`).test(src);
  check(`"${name}" is a variable that actually exists`, declared,
        `nothing declares ${name}; the step would always render empty`);
}

// --- run the gating logic ----------------------------------------------
// Extract the real functions and execute them, so the assertions are
// about behaviour rather than about source text.
const maybeShowSrc = (src.match(/function maybeShowWizard\(\)\s*\{[\s\S]*?\n\}/) || [])[0];
const closeSrc = (src.match(/function closeWizard\(alsoSuppressTour\)\s*\{[\s\S]*?\n\}/) || [])[0];
check("maybeShowWizard body extracted", !!maybeShowSrc);
check("closeWizard body extracted", !!closeSrc);

function fakeStorage(initial) {
  const store = { ...initial };
  return {
    store,
    api: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    },
  };
}

function runGate(initial) {
  const fs_ = fakeStorage(initial);
  const ctx = {
    localStorage: fs_.api,
    setTimeout: () => 0,
    document: { getElementById: () => null },
    console: { log() {}, warn() {}, error() {} },
  };
  vm.runInNewContext(`
    const TOUR_KEY = ${JSON.stringify(TOUR_KEY)};
    const WIZ_KEY  = ${JSON.stringify(WIZ_KEY)};
    function openWizard() {}
    ${maybeShowSrc}
    var shown = maybeShowWizard();
  `, ctx, { timeout: 4000 });
  return { shown: ctx.shown, store: fs_.store };
}

if (maybeShowSrc) {
  check("fresh install: the wizard is offered", runGate({}).shown === true);
  check("already completed: not offered again",
        runGate({ [WIZ_KEY]: "1" }).shown === false);
  check("upgrading user who saw the tour: not offered",
        runGate({ [TOUR_KEY]: "1" }).shown === false,
        "an existing user must not be greeted by a setup wizard");
}

function runClose(suppressTour) {
  const fs_ = fakeStorage({});
  const ctx = {
    localStorage: fs_.api,
    document: { getElementById: () => null },
    console: { log() {}, warn() {}, error() {} },
  };
  vm.runInNewContext(`
    const TOUR_KEY = ${JSON.stringify(TOUR_KEY)};
    const WIZ_KEY  = ${JSON.stringify(WIZ_KEY)};
    function _wizEl() { return null; }
    ${closeSrc}
    closeWizard(${suppressTour});
  `, ctx, { timeout: 4000 });
  return fs_.store;
}

if (closeSrc) {
  const skipped = runClose(true);
  check("skipping marks the wizard seen", skipped[WIZ_KEY] === "1");
  check("skipping suppresses the tour too", skipped[TOUR_KEY] === "1",
        "dismissing one intro must not hand you the other");

  const finished = runClose(false);
  check("finishing marks the wizard seen", finished[WIZ_KEY] === "1");
  check("finishing leaves the tour available",
        finished[TOUR_KEY] === undefined,
        "the last step offers the tour, so it must not be pre-suppressed");
}

// --- the steps themselves ----------------------------------------------
const lookIds = src.match(/const WIZ_LOOK_IDS\s*=\s*\[([^\]]*)\]/);
check("WIZ_LOOK_IDS is declared", !!lookIds);
if (lookIds) {
  const ids = [...lookIds[1].matchAll(/"([\w-]+)"/g)].map(m => m[1]);
  check("offers a small number of Looks, not all of them",
        ids.length >= 3 && ids.length <= 5, `offers ${ids.length}`);
  // Every offered id must exist in LOOK_BUNDLES, or the step silently
  // renders fewer choices than intended.
  const bundleIds = [...src.matchAll(/^\s{4}id:\s*"([\w-]+)"/gm)].map(m => m[1]);
  const bogus = ids.filter(i => !bundleIds.includes(i));
  check("every offered Look exists in LOOK_BUNDLES", bogus.length === 0,
        bogus.length ? `unknown: ${bogus.join(", ")}` : `checked against ${bundleIds.length}`);
}

// Each step needs both translation keys in both languages, or the panel
// renders blank headings.
for (const step of ["look", "bg", "done"]) {
  for (const part of ["title", "body"]) {
    const key = `wizard.${step}.${part}`;
    const entry = src.match(
      new RegExp(`"${key.replace(/\./g, "\\.")}":\\s*\\{[\\s\\S]{0,700}?\\}`));
    check(`${key} exists in both languages`,
          !!entry && /en:\s*"/.test(entry[0]) && /de:\s*"/.test(entry[0]));
  }
}
for (const key of ["wizard.step", "wizard.next", "wizard.skip", "wizard.finish"]) {
  // `[^}]*` would stop at the first brace, and these strings contain
  // {n} / {total} placeholders — so the entry looks absent when it is
  // merely interpolated.
  const entry = src.match(
    new RegExp(`"${key.replace(/\./g, "\\.")}":\\s*\\{[\\s\\S]{0,300}?\\},`));
  check(`${key} exists in both languages`,
        !!entry && /en:\s*"/.test(entry[0]) && /de:\s*"/.test(entry[0]));
}

// The overlay must live outside <main>, or the tab display rules hide
// it. Match the real element, not the several comments and CSS
// selectors that spell "<main" in prose — the first textual hit is a
// comment on line 191, which put the boundary ~2400 lines too early
// and made a correctly-placed overlay look nested.
// Comments are stripped first: line 191 contains the prose "…above
// <main>. Five tabs…", which matches a start-tag pattern perfectly well
// and put the boundary ~2400 lines too early, making a correctly-placed
// overlay look nested. Offsets are compared within the stripped copy so
// both ends refer to the same text.
// <style> blocks go too, not just HTML comments: the prose that
// matched was inside a CSS comment ("…horizontal tab row above
// <main>. Five tabs filter…"), which /* */ hides from the HTML comment
// stripper but not from a tag scan.
const stripped = HTML
  .replace(/<style[\s\S]*?<\/style>/gi, "")
  .replace(/<!--[\s\S]*?-->/g, "");
const mainStart = stripped.search(/<main\b[^>]*>/);
const mainEnd = stripped.indexOf("</main>");
const wizAt = stripped.indexOf('id="wiz-overlay"');
check("found the real <main> element", mainStart > 0 && mainEnd > mainStart);
check("wizard overlay exists in the markup", wizAt > 0);
check("wizard overlay is outside <main>",
      wizAt > 0 && !(wizAt > mainStart && wizAt < mainEnd),
      "inside <main> the tab display rules would hide it");

console.error("\n" + "=".repeat(68));
console.error(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
