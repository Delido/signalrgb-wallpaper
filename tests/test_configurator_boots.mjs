// The Configurator's script must still run after the redesign.
//
// WHY THIS EXISTS
//
// v2.4.4-beta.7 shipped a wallpaper page that was completely dead: a
// refactor removed a block that happened to carry `let gridRenderer`,
// so the first reference threw a ReferenceError under "use strict"
// during init. Black screen, "bridge offline" card. Every structural
// check in the suite passed, because the markup was fine — nothing
// actually RAN the code.
//
// The task-oriented redesign moves cards between tabs, splits a card in
// two and rewrites the tab table. That is the same class of change, on
// a file with 8.800 lines of script and 162 ids the JS looks up. So the
// Configurator gets the same treatment the wallpaper page got: execute
// the script in a sandbox and assert it reaches the end.
//
// This is a smoke test, not a functional one. It cannot tell you the UI
// is usable — only that it is not dead on arrival, which is exactly the
// failure mode structural tests are blind to.

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

console.error("\nConfigurator boots\n" + "=".repeat(68));

// Take the largest inline <script> — the main application block.
//
// HTML comments are stripped first. A comment at configurator.html:2450
// mentions "<script>" in prose, and without this the scan opens a block
// there and hands the following comment text to the parser as code —
// which surfaced as a bogus `SyntaxError: Unexpected identifier 'its'`
// pointing at English rather than at any real defect.
const noComments = HTML.replace(/<!--[\s\S]*?-->/g, "");
const scripts = [...noComments.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]);
check("inline scripts found", scripts.length > 0, `found ${scripts.length}`);
const src = scripts.sort((a, b) => b.length - a.length)[0];
check("main script block is substantial", src.length > 100000, `${src.length} chars`);

// A permissive stub: every property access returns another callable
// proxy, so DOM chains resolve without modelling the DOM.
const stub = () => new Proxy(function () {}, {
  get: (t, k) => {
    if (k === "length") return 0;
    if (k === Symbol.toPrimitive) return () => "";
    if (k === "classList") return { add() {}, remove() {}, toggle() {}, contains: () => false };
    if (k === "style") return new Proxy({}, { get: () => () => {}, set: () => true });
    if (k === "dataset") return new Proxy({}, { get: () => "", set: () => true });
    if (k === "then") return undefined;          // must not look thenable
    if (k === "options") return [];
    if (k === "value") return "";
    return stub();
  },
  apply: () => stub(),
  construct: () => stub(),
  set: () => true,
});

const ctx = {
  console: { log() {}, warn() {}, error() {}, info() {}, debug() {} },
  setTimeout: () => 0, setInterval: () => 0, clearTimeout() {}, clearInterval() {},
  requestAnimationFrame: () => 0, cancelAnimationFrame() {},
  performance: { now: () => 0 },
  Date, Math, JSON, Intl, Promise, URLSearchParams, URL, TextEncoder, TextDecoder,
  document: stub(), window: stub(),
  navigator: { userAgent: "test", language: "de", clipboard: stub() },
  location: { search: "", href: "http://127.0.0.1:17320/configurator",
              hostname: "127.0.0.1", hash: "" },
  WebSocket: function () { return stub(); },
  Image: function () { return stub(); },
  FormData: function () { return stub(); },
  FileReader: function () { return stub(); },
  Blob: function () { return stub(); },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}),
                                 text: () => Promise.resolve("") }),
  ResizeObserver: function () { return stub(); },
  MutationObserver: function () { return stub(); },
  IntersectionObserver: function () { return stub(); },
  getComputedStyle: () => stub(),
  CustomEvent: function () { return stub(); },
  Event: function () { return stub(); },
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  devicePixelRatio: 1, innerWidth: 1600, innerHeight: 900,
  alert() {}, confirm: () => false, prompt: () => null,
};
ctx.globalThis = ctx;
ctx.self = ctx;

let initError = null;
try {
  vm.runInNewContext(src, vm.createContext(ctx), { timeout: 15000 });
} catch (e) {
  initError = `${e.constructor.name}: ${e.message}`.slice(0, 200);
}
check("script runs to completion without throwing", initError === null, initError || "");

// The redesign's own moving parts, named individually so a failure
// points at the cause rather than at a generic ReferenceError.
check("SECTION_TABS is declared", /const SECTION_TABS\s*=\s*\[/.test(src));
check("LEGACY_TAB_ALIASES is declared", /const LEGACY_TAB_ALIASES\s*=/.test(src));
check("TOUR_STEPS is declared", /const TOUR_STEPS\s*=\s*\[/.test(src));

// Every tab key referenced by a card must be declared, and vice versa —
// a tab with no cards renders an empty page, a card with no tab never
// shows at all. Compared against the markup, not against a copy here.
const declared = [...src.matchAll(/\{\s*key:\s*"([\w-]+)",\s*i18n:/g)].map(m => m[1]);
// Only count real <section> cards. The CSS show/hide rule also spells
// data-section-tab="…" for every tab, so scanning the whole file makes
// every declared tab look populated and the check can never fail.
const cardTags = [...HTML.matchAll(/<section\b[^>]*data-section-tab="([\w-]+)"[^>]*>/g)];
const used = [...new Set(cardTags.map(m => m[1]))];
check("every declared tab has at least one card",
      declared.every(t => used.includes(t)),
      `declared ${declared.join(",")} / used ${used.join(",")}`);
check("every used tab is declared",
      used.every(t => declared.includes(t)),
      `orphans: ${used.filter(t => !declared.includes(t)).join(",")}`);

// Legacy aliases must resolve to real tabs, or a returning user with a
// stored "look" lands nowhere.
const aliasBlock = src.match(/const LEGACY_TAB_ALIASES\s*=\s*\{([\s\S]*?)\}/);
if (aliasBlock) {
  const targets = [...aliasBlock[1].matchAll(/:\s*"([\w-]+)"/g)].map(m => m[1]);
  check("every legacy alias points at a declared tab",
        targets.every(t => declared.includes(t)),
        `bad: ${targets.filter(t => !declared.includes(t)).join(",")}`);
  const sources = [...aliasBlock[1].matchAll(/(\w+)\s*:/g)].map(m => m[1]);
  for (const old of ["look", "library", "effects", "widgets", "integrations"]) {
    check(`legacy tab "${old}" still resolves`, sources.includes(old));
  }
}

console.error("\n" + "=".repeat(68));
console.error(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
