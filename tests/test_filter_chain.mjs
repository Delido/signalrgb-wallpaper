// CSS `filter` collisions on the glow layers.
//
// WHY THIS EXISTS
//
// `filter` is a single property, not a list that merges. When two rules
// both set it on the same element, the more specific one REPLACES the
// other — it does not add to it. That is easy to miss, because the two
// rules usually live hundreds of lines apart and each looks correct.
//
// It bit in v2.4.4-beta.14. Turning on Liquid Distortion set
// `body.fx-ripple #bars { filter: url(#fx-ripple-filter) }` at
// specificity 410, which beat `#bars.lay-grid { filter: blur(...) }` at
// 110. The glow lost its blur entirely and the bare grid cells showed
// as hard blocks — reported as "wenn ich flüssige verzerrung aktiviere,
// ist der glow wieder kästchen gebröckelt".
//
// The irony: beta.14 had just renamed the Spread slider to explain that
// exact artefact, and this was a second, unrelated way to produce it.
//
// So this suite parses the real stylesheet, resolves the cascade for
// every glow-carrying element under every combination of body-level
// effect classes, and asserts the winning declaration still contains a
// blur. It is deliberately about the RESOLVED value, not about whether
// some particular rule exists: a future effect that adds another
// body-level filter rule would reintroduce the bug, and grepping for
// today's selectors would not catch it.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const CSS = readFileSync(
  join(HERE, "..", "wallpaper_bridge", "wallpaper", "index.html"), "utf8");

let pass = 0, fail = 0;
function check(label, ok, detail) {
  if (ok) { pass++; console.error(`  ok    ${label}`); }
  else { fail++; console.error(`  FAIL  ${label}${detail ? "\n          " + detail : ""}`); }
}

// --- a small cascade resolver ------------------------------------------
// Enough CSS to model these rules: id/class counts for specificity, and
// document order to break ties. No pseudo-classes are involved here.
function specificity(sel) {
  const ids = (sel.match(/#[\w-]+/g) || []).length;
  const cls = (sel.match(/\.[\w-]+/g) || []).length;
  return ids * 100 + cls * 10;
}

function filterRules() {
  // Strip comments first — several contain braces and `filter:` in prose.
  const clean = CSS.replace(/\/\*[\s\S]*?\*\//g, "");
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m, order = 0;
  while ((m = re.exec(clean))) {
    const decl = m[2].match(/(?:^|;|\s)filter\s*:\s*([^;]+)/);
    if (!decl) continue;
    for (const sel of m[1].split(",").map(s => s.trim().replace(/\s+/g, " "))) {
      if (!sel || sel.startsWith("@")) continue;
      out.push({ sel, value: decl[1].trim(), spec: specificity(sel), order: order++ });
    }
  }
  return out;
}

// Does `sel` match an element with these classes, given body classes?
function matches(sel, el, bodyClasses) {
  const parts = sel.split(" ").filter(Boolean);
  const last = parts[parts.length - 1];
  // The subject: "#bars.lay-grid" -> id #bars plus class lay-grid
  const wantId = (last.match(/#[\w-]+/) || [])[0];
  const wantCls = (last.match(/\.[\w-]+/g) || []).map(c => c.slice(1));
  if (wantId && wantId !== el.id) return false;
  if (!wantId && last.startsWith(".")) {
    // e.g. "#bars.lay-vstripes .zone" — subject is .zone
    if (!el.classes.includes(last.slice(1))) return false;
  } else if (wantCls.some(c => !el.classes.includes(c))) return false;

  // Ancestors: every earlier part must be satisfied by body or #bars.
  for (const anc of parts.slice(0, -1)) {
    const ancId = (anc.match(/#[\w-]+/) || [])[0];
    const ancCls = (anc.match(/\.[\w-]+/g) || []).map(c => c.slice(1));
    if (anc.startsWith("body")) {
      if (ancCls.some(c => !bodyClasses.includes(c))) return false;
    } else if (ancId) {
      if (ancId !== el.parentId) return false;
      if (ancCls.some(c => !(el.parentClasses || []).includes(c))) return false;
    } else return false;
  }
  return true;
}

function resolve(el, bodyClasses) {
  const cands = filterRules().filter(r => matches(r.sel, el, bodyClasses));
  if (!cands.length) return null;
  cands.sort((a, b) => (a.spec - b.spec) || (a.order - b.order));
  return cands[cands.length - 1];
}

console.error("\nGlow filter chain\n" + "=".repeat(68));

// The elements that actually carry the glow, per layout.
const GLOW_ELEMENTS = [
  { label: "grid / #bars",        el: { id: "#bars", classes: ["lay-grid"] } },
  { label: "grid / #bars-canvas", el: { id: "#bars-canvas", classes: [] } },
  { label: "vstripes / .zone",    el: { id: null, classes: ["zone"],
                                        parentId: "#bars", parentClasses: ["lay-vstripes"] } },
  { label: "hstripes / .zone",    el: { id: null, classes: ["zone"],
                                        parentId: "#bars", parentClasses: ["lay-hstripes"] } },
];

// Every body-level effect class that sets a filter somewhere.
const BODY_STATES = [
  { label: "no effect",           classes: [] },
  { label: "fx-ripple",           classes: ["fx-ripple"] },
  { label: "fx-pixelfx-water",    classes: ["fx-pixelfx-water"] },
  { label: "both effects",        classes: ["fx-ripple", "fx-pixelfx-water"] },
];

for (const { label, el } of GLOW_ELEMENTS) {
  for (const state of BODY_STATES) {
    const win = resolve(el, state.classes);
    const has = win && /blur\(/.test(win.value);
    check(`${label} keeps its blur with ${state.label}`, !!has,
          win ? `winner: ${win.sel}\n          -> ${win.value.slice(0, 80)}`
              : "no filter rule matched at all");
  }
}

// The distortion must still reach the grid — a fix that dropped the
// displacement to save the blur would pass the checks above.
const ripGrid = resolve(GLOW_ELEMENTS[0].el, ["fx-ripple"]);
check("grid is still displaced under fx-ripple",
      !!ripGrid && /url\(#fx-ripple-filter\)/.test(ripGrid.value),
      ripGrid ? ripGrid.value : "");

// Order within the chain: displace, then blur. The reverse would let
// the displacement re-sharpen edges the blur had just softened.
if (ripGrid && /blur\(/.test(ripGrid.value) && /url\(/.test(ripGrid.value)) {
  check("displacement is applied before the blur",
        ripGrid.value.indexOf("url(") < ripGrid.value.indexOf("blur("),
        ripGrid.value);
}

// #bg must NOT gain a blur — it is the background photo, not a glow layer.
const bgRip = resolve({ id: "#bg", classes: [] }, ["fx-ripple"]);
check("#bg is displaced but never blurred",
      !!bgRip && /url\(#fx-ripple-filter\)/.test(bgRip.value) && !/blur\(/.test(bgRip.value),
      bgRip ? bgRip.value : "no rule");

console.error("\n" + "=".repeat(68));
console.error(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
