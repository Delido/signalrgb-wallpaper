// Every setting must stay reachable, whatever the layout looks like.
//
// WHY THIS EXISTS
//
// This is a characterisation test, written BEFORE the task-oriented
// redesign moved anything, and it has to keep passing unmodified
// afterwards. Same discipline as test_http_routing.py before the
// handle_client split: a test that needs adjusting to pass after the
// change has stopped characterising anything.
//
// Reorganising ~59 controls across 12 cards is exactly the kind of
// change whose mistakes are silent. Nothing crashes when a slider ends
// up in the wrong tab or loses its label — it just quietly becomes
// unfindable, and the only signal is a user eventually asking where it
// went. That is not a signal a test suite can wait for.
//
// So this asserts the invariants that must survive any layout:
//
//   * every control the JS talks to still exists in the markup
//   * every control lives inside some card, and every card inside a tab
//   * every control still has a label bound to it
//   * the settings the bridge accepts all have a control somewhere
//
// It deliberately does NOT assert which tab a control is in. That is
// the thing the redesign is allowed to change.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, "..");
const HTML = readFileSync(join(REPO, "wallpaper_bridge", "configurator.html"), "utf8");
const BRIDGE = readFileSync(join(REPO, "wallpaper_bridge", "bridge.py"), "utf8");

let pass = 0, fail = 0;
function check(label, ok, detail) {
  if (ok) { pass++; console.error(`  ok    ${label}`); }
  else { fail++; console.error(`  FAIL  ${label}${detail ? "\n          " + detail : ""}`); }
}

const mainStart = HTML.indexOf("<main");
const mainEnd = HTML.indexOf("</main>");
const MARKUP = HTML.slice(mainStart, mainEnd);

console.error("\nSettings reachability\n" + "=".repeat(68));
check("<main> block found", mainStart > 0 && mainEnd > mainStart);

// --- cards and their tabs ---------------------------------------------
const cards = [];
for (const m of MARKUP.matchAll(/<section\b[^>]*>/gs)) {
  const tag = m[0];
  if (!/class="[^"]*card/.test(tag)) continue;
  const id = (tag.match(/id="([\w-]+)"/) || [])[1];
  const tab = (tag.match(/data-section-tab="([\w-]+)"/) || [])[1];
  cards.push({ id, tab, at: m.index });
}
cards.sort((a, b) => a.at - b.at);

check("cards are present", cards.length > 0, `found ${cards.length}`);
const orphanCards = cards.filter(c => !c.tab);
check("every card is assigned to a tab", orphanCards.length === 0,
      orphanCards.map(c => c.id).join(", "));
const unnamed = cards.filter(c => !c.id);
check("every card has an id", unnamed.length === 0);

// Tabs referenced by cards must exist in SECTION_TABS.
const declaredTabs = [...HTML.matchAll(/\{\s*key:\s*"([\w-]+)"\s*,\s*i18n:/g)].map(m => m[1]);
check("SECTION_TABS declares tabs", declaredTabs.length > 0, declaredTabs.join(", "));
const usedTabs = [...new Set(cards.map(c => c.tab).filter(Boolean))];
const unknownTabs = usedTabs.filter(t => !declaredTabs.includes(t));
check("no card points at an undeclared tab", unknownTabs.length === 0,
      unknownTabs.join(", "));

// The CSS show/hide rule must cover every declared tab, or a whole tab
// renders blank — the failure mode is invisible until someone clicks it.
for (const tab of declaredTabs) {
  check(`CSS reveals cards of tab "${tab}"`,
        HTML.includes(`main[data-active-tab="${tab}"]`),
        "missing from the display:block rule");
}

// --- controls ----------------------------------------------------------
// Every control that lives in a card, with the card it belongs to.
const controls = [];
for (let i = 0; i < cards.length; i++) {
  const seg = MARKUP.slice(cards[i].at, i + 1 < cards.length ? cards[i + 1].at : MARKUP.length);
  for (const m of seg.matchAll(/<(input|select|textarea)\b[^>]*id="([\w-]+)"[^>]*>/g)) {
    controls.push({ tag: m[1], id: m[2], card: cards[i].id, tab: cards[i].tab });
  }
}
check("controls found inside cards", controls.length >= 50, `found ${controls.length}`);

// Everything the JS looks up by id must exist in the markup. This is the
// check that catches a control deleted or renamed during a move.
const referenced = new Set();
for (const m of HTML.matchAll(/\$\("([\w-]+)"\)/g)) referenced.add(m[1]);
for (const m of HTML.matchAll(/getElementById\("([\w-]+)"\)/g)) referenced.add(m[1]);

const presentIds = new Set([...HTML.matchAll(/id="([\w-]+)"/g)].map(m => m[1]));
// Some elements are built at runtime (the tour overlay, the floating
// preview, hwmon sensor rows). They never appear in the markup, so an
// id that the JS both creates and looks up is not dangling.
const createdAtRuntime = new Set(
  [...HTML.matchAll(/\.id\s*=\s*"([\w-]+)"/g)].map(m => m[1]));
// Also ids that appear inside JS-built HTML strings, where the source
// spells them id=\"…\" — innerHTML assembly rather than createElement.
for (const m of HTML.matchAll(/id=\\"([\w-]+)\\"/g)) createdAtRuntime.add(m[1]);
// …and ids assembled with setAttribute.
for (const m of HTML.matchAll(/setAttribute\("id",\s*"([\w-]+)"/g)) createdAtRuntime.add(m[1]);
// Widget-option fields are built as "f-" + key inside openOptionsModal,
// so their ids exist only for as long as that modal is open and never
// appear in the markup. The lookups guard with `if (!sel) return`.
const isModalField = (id) => /^f-[A-Za-z]/.test(id);
const missing = [...referenced].filter(
  id => !presentIds.has(id) && !createdAtRuntime.has(id) && !isModalField(id));
check("every id the JS references exists in the markup",
      missing.length === 0,
      missing.length ? `dangling: ${missing.slice(0, 12).join(", ")}` : "");

// Labels: a control with no label is unusable regardless of where it
// sits. Four spellings count, all of them in use here:
//   <label for="x">      explicit binding
//   <label><input>…      the label wraps the control
//   aria-label / title / placeholder on the control itself
//   a <select> whose <option>s carry the wording
// Note `\\b` — inside a template string a lone \b is a backspace
// character, not a word boundary, which silently matches nothing.
const unlabelled = controls.filter(c => {
  const tag = MARKUP.match(
    new RegExp(`<(?:input|select|textarea)\\b[^>]*id="${c.id}"[^>]*>`));
  if (!tag) return true;                       // control vanished entirely
  if (/type="(hidden|file)"/.test(tag[0])) return false;  // button-driven
  if (MARKUP.includes(`for="${c.id}"`)) return false;
  if (/aria-label=|title=|placeholder=|data-i18n/.test(tag[0])) return false;

  // Wrapping label: walk back from the control to the nearest tag and
  // see whether an unclosed <label> encloses it.
  const at = MARKUP.indexOf(tag[0]);
  const before = MARKUP.slice(Math.max(0, at - 400), at);
  if (before.lastIndexOf("<label") > before.lastIndexOf("</label>")) return false;

  // <select> labelled by its own options.
  if (c.tag === "select") {
    const after = MARKUP.slice(at, at + 600);
    if (/<option[^>]*data-i18n=/.test(after)) return false;
  }
  return true;
});
check("every visible control has a label or aria-label",
      unlabelled.length === 0,
      unlabelled.length ? unlabelled.map(c => `${c.id} (${c.card})` ).slice(0, 10).join(", ") : "");

// --- the bridge's settings must all be operable -------------------------
// _SETTABLE_SCREEN_KEYS is the contract: what the bridge will accept per
// screen. A key with no way to set it is a dead feature.
const keyBlock = BRIDGE.match(/_SETTABLE_SCREEN_KEYS\s*=\s*\{([\s\S]*?)\}/);
check("_SETTABLE_SCREEN_KEYS found in bridge.py", !!keyBlock);
if (keyBlock) {
  const keys = [...keyBlock[1].matchAll(/"([a-zA-Z][\w]*)"/g)].map(m => m[1]);
  check("bridge exposes the expected number of screen settings",
        keys.length >= 30, `found ${keys.length}`);

  // Each key must be handled somewhere in the Configurator's JS —
  // either sent through the settings path or named in a preset bundle.
  const unhandled = keys.filter(k => {
    const re = new RegExp(`["'\`]${k}["'\`]|\b${k}\s*:`);
    return !re.test(HTML);
  });
  check("every bridge setting is named in the Configurator",
        unhandled.length === 0,
        unhandled.length ? `unreachable: ${unhandled.join(", ")}` : "");
}

console.error("\n" + "=".repeat(68));
console.error(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
