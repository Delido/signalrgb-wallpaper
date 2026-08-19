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

  // Naming a key is weaker than writing it: a key could survive only in
  // a comment or a preset table. Assert that all but a known few are
  // actually pushed to the bridge by a control.
  //
  // The exceptions are set through their own paths rather than a
  // labelled control, which is correct and not a gap:
  //   bgImageUrl    — written by the library when a picture is applied
  //   widgetsLocked — written by the padlock toggle in the widget bar
  const writes = new Set([
    ...[...HTML.matchAll(/setSetting\("(\w+)"/g)].map(m => m[1]),
    ...[...HTML.matchAll(/bindRangeChange\(els\.\w+,\s*els\.\w+,\s*"(\w+)"/g)].map(m => m[1]),
  ]);
  const INDIRECT = new Set(["bgImageUrl", "widgetsLocked"]);
  const neverWritten = keys.filter(k => !writes.has(k) && !INDIRECT.has(k));
  check("every setting is written by some control",
        neverWritten.length === 0,
        neverWritten.length ? `named but never sent: ${neverWritten.join(", ")}` : "");

  // And the indirect two must still be written somewhere, or the
  // exemption above quietly becomes a hiding place.
  for (const k of INDIRECT) {
    check(`${k} is still assigned somewhere`,
          new RegExp(`(?:settings\\.${k}\\s*=|"${k}"\\s*[,:\\]])`).test(HTML));
  }
}

// --- container elements must not straddle a card boundary --------------
// Splitting card-system into two cards cut straight through a
// <details><summary>…</summary>, leaving an unclosed <details> in one
// card and a stray </details> in the next. The browser repairs that by
// rendering an empty collapsible box — which is exactly what showed up
// under the System card, and what nothing in this suite noticed:
// the markup still parsed, every control still existed, every id still
// resolved.
//
// So: count opening and closing tags per card. Any imbalance means a
// container was cut in half.
for (const tag of ["details", "section", "div"]) {
  const opens = tag === "div"
    ? null   // div counts are dominated by layout noise; skip the pairing
    : new RegExp(`<${tag}\\b`, "g");
  if (!opens) continue;
  for (let i = 0; i < cards.length; i++) {
    const seg = MARKUP.slice(cards[i].at,
                             i + 1 < cards.length ? cards[i + 1].at : MARKUP.length);
    // The card's own <section> is excluded by starting the count after it.
    const body = tag === "section" ? seg.slice(seg.indexOf(">") + 1) : seg;
    const nOpen = (body.match(new RegExp(`<${tag}\\b`, "g")) || []).length;
    const nClose = (body.match(new RegExp(`</${tag}>`, "g")) || []).length;
    if (tag === "section" && nOpen === 0 && nClose === 1) continue;  // own closer
    check(`${cards[i].id}: <${tag}> tags are balanced`,
          nOpen === nClose, `${nOpen} open vs ${nClose} close`);
  }
}

// A <summary> must sit inside a <details> and contain its heading. A cut
// through the summary leaves a heading orphaned outside any details.
const summaries = [...MARKUP.matchAll(/<summary\b[^>]*>([\s\S]{0,200}?)<\/summary>/g)];
check("every <summary> is well-formed",
      summaries.every(m => !/<\/(?:div|section)>/.test(m[1])),
      "a summary containing a closing div/section means the split cut through it");

// --- collapsed "More settings" blocks ----------------------------------
// Phase 3 hides the controls most people never touch behind a per-card
// toggle. Hidden is fine; unreachable is not. Every .adv-body needs a
// toggle immediately before it, or its contents can never be opened —
// and that failure is invisible, because the markup still parses and
// the controls still exist.
const advBodies = [...MARKUP.matchAll(/<div class="adv-body">/g)];
const advToggles = [...MARKUP.matchAll(/<button class="adv-toggle"[^>]*>/g)];
check("every advanced block has a toggle",
      advBodies.length === advToggles.length,
      `${advBodies.length} bodies vs ${advToggles.length} toggles`);

for (const m of advBodies) {
  const before = MARKUP.slice(Math.max(0, m.index - 260), m.index);
  check("an adv-body is preceded by its toggle",
        /<button class="adv-toggle"[\s\S]*<\/button>\s*$/.test(before),
        before.slice(-90).replace(/\s+/g, " "));
}

// The toggle needs the label span the JS writes into, or the button
// renders empty and reads as a stray line.
for (const m of advToggles) {
  const after = MARKUP.slice(m.index, m.index + 300);
  check("an adv-toggle carries an .adv-label span",
        /class="adv-label"/.test(after), after.slice(0, 90).replace(/\s+/g, " "));
}

// Both label strings must exist, since the button text is set from
// them at runtime rather than living in the markup.
for (const key of ["adv.show", "adv.hide"]) {
  const entry = HTML.match(new RegExp(`"${key.replace(".", "\\.")}":\\s*\\{[^}]*\\}`));
  check(`${key} is translated in both languages`,
        !!entry && /en:\s*"/.test(entry[0]) && /de:\s*"/.test(entry[0]));
}

// Whatever is collapsed must still be a control the bridge knows about
// — the point is to tidy, not to bury something that then looks broken.
const advIds = [];
for (const m of advBodies) {
  const seg = MARKUP.slice(m.index, m.index + 4000);
  for (const c of seg.matchAll(/<(?:input|select)\b[^>]*id="([\w-]+)"/g)) advIds.push(c[1]);
}
check("collapsed blocks actually contain controls", advIds.length > 5,
      `found ${advIds.length}`);

// --- the guided tour must point at things that exist -------------------
// Each TOUR_STEPS entry names a card selector and, optionally, the tab
// to switch to first. When the two disagree the step activates a tab
// that never shows that card, so the spotlight lands on nothing and the
// tour silently degrades. card-presets did exactly this: the step named
// tab "system" while the card lives in "look".
const cardTab = new Map(cards.filter(c => c.id).map(c => [c.id, c.tab]));
const tourBlock = HTML.slice(HTML.indexOf("const TOUR_STEPS"));
const steps = [...tourBlock.slice(0, tourBlock.indexOf("];")).matchAll(
  /selector:\s*"#([\w-]+)"(?:[^}\n]*?tab:\s*"([\w-]+)")?/g)];
check("TOUR_STEPS parsed", steps.length > 3, `found ${steps.length}`);

const badTarget = steps.filter(m => !presentIds.has(m[1]));
check("every tour step points at an element that exists",
      badTarget.length === 0, badTarget.map(m => "#" + m[1]).join(", "));

const wrongTab = steps.filter(m => m[2] && cardTab.has(m[1]) && cardTab.get(m[1]) !== m[2]);
check("every tour step names the tab its card actually lives in",
      wrongTab.length === 0,
      wrongTab.map(m => `#${m[1]}: step says "${m[2]}", card is in "${cardTab.get(m[1])}"`).join("; "));

console.error("\n" + "=".repeat(68));
console.error(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
