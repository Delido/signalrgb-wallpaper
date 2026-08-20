// Per-screen chrome must not appear on bridge-global tabs.
//
// WHY THIS EXISTS
//
// The screen tab strip ("Screen 1 — 2560×1440 | Screen 2 — …") wraps the
// whole page, including tabs whose settings are not per-screen at all.
// System and Connections are bridge-global to the last control: the
// language, update checks, the API token, OpenRGB, sACN and MQTT are one
// setting each for the entire app.
//
// Showing a screen selector above them is worse than useless — it
// implies screen 2 has its own language and its own OpenRGB connection,
// and that switching tabs before changing something matters. Reported
// as "praktisch ist es falsch das das system Bereich in dem Monitor Tab
// vorhanden ist oder?", extended to Connections in the same breath.
//
// The classification is derived from the markup rather than restated
// here: a tab counts as global when none of its controls writes a
// per-screen setting. If someone later drops a per-screen control into
// System, that is a real design question and the test should force it
// to be answered rather than silently keeping the strip hidden.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const HTML = readFileSync(
  join(HERE, "..", "wallpaper_bridge", "configurator.html"), "utf8");

let pass = 0, fail = 0;
function check(label, ok, detail) {
  if (ok) { pass++; console.error(`  ok    ${label}`); }
  else { fail++; console.error(`  FAIL  ${label}${detail ? "\n          " + detail : ""}`); }
}

console.error("\nTab scope\n" + "=".repeat(68));

const mainStart = HTML.indexOf('<main data-active-tab');
const MARKUP = HTML.slice(mainStart, HTML.indexOf("</main>"));

// --- work out which tabs are global, from the markup ------------------
const cards = [];
for (const m of MARKUP.matchAll(/<section\b[^>]*>/gs)) {
  if (!/class="[^"]*card/.test(m[0])) continue;
  const id = (m[0].match(/id="([\w-]+)"/) || [])[1];
  const tab = (m[0].match(/data-section-tab="([\w-]+)"/) || [])[1];
  if (tab) cards.push({ id, tab, at: m.index });
}
cards.sort((a, b) => a.at - b.at);
check("cards found", cards.length > 5, `${cards.length}`);

// What makes a control per-screen is that it writes a per-screen
// setting — i.e. the JS reaches it via els.<name> and calls setSetting()
// with it. Classifying by id prefix instead looks tidier and is wrong:
// profile-add-btn (sends profile-add with screen:null) and
// restore-upload (a backup file input) are both app-wide but match no
// bridge-level prefix, which made a correct System tab fail this test.
const camel = (id) => id.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const writesPerScreen = (id) => {
  const name = camel(id);
  // setSetting("key", …) driven by this element, in either order.
  const re = new RegExp(
    `els\\.${name}\\b[\\s\\S]{0,400}?setSetting\\(|setSetting\\([^)]*els\\.${name}\\b`);
  return re.test(HTML);
};

const perTab = new Map();
for (let i = 0; i < cards.length; i++) {
  const seg = MARKUP.slice(cards[i].at,
                           i + 1 < cards.length ? cards[i + 1].at : MARKUP.length);
  const ids = [...seg.matchAll(/<(?:input|select|button)\b[^>]*id="([\w-]+)"/g)]
    .map(m => m[1]);
  const cur = perTab.get(cards[i].tab) || { total: 0, global: 0, perScreen: [] };
  for (const id of ids) {
    cur.total++;
    if (writesPerScreen(id)) cur.perScreen.push(id);
    else cur.global++;
  }
  perTab.set(cards[i].tab, cur);
}

const derivedGlobal = [...perTab.entries()]
  .filter(([, v]) => v.total > 0 && v.global === v.total)
  .map(([k]) => k).sort();
check("some tabs are entirely bridge-global", derivedGlobal.length > 0,
      derivedGlobal.join(", "));

// --- and the code must agree -------------------------------------------
const declared = HTML.match(/const GLOBAL_TABS = new Set\(\[([^\]]*)\]\)/);
check("GLOBAL_TABS is declared", !!declared);
if (declared) {
  const listed = [...declared[1].matchAll(/"([\w-]+)"/g)].map(m => m[1]).sort();
  check("GLOBAL_TABS matches what the markup implies",
        JSON.stringify(listed) === JSON.stringify(derivedGlobal),
        `declared [${listed}] vs derived [${derivedGlobal}]`);
  // Guard the other direction too: a tab with per-screen controls must
  // never be listed, or its screen picker disappears and the user can
  // only ever edit screen 1.
  for (const tab of listed) {
    const v = perTab.get(tab);
    check(`"${tab}" really has no per-screen controls`,
          !!v && v.global === v.total,
          v ? `per-screen: ${v.perScreen.join(", ")}` : "tab not found");
  }
}

// --- the chrome actually gets hidden ------------------------------------
check("a scope helper exists", /function _applyScreenScopeChrome\(/.test(HTML));
check("it is called from activateSectionTab",
      /function activateSectionTab\(key\)\s*\{[\s\S]{0,300}?_applyScreenScopeChrome\(key\)/
        .test(HTML),
      "declaring it without calling it changes nothing");
check("it hides the screen tab strip",
      /getElementById\("tabs"\)[\s\S]{0,200}?display = global \? "none" : ""/.test(HTML));

// Hiding the strip with no explanation reads as a glitch, so a note
// takes its place.
check("a replacement note exists in the markup",
      /id="global-scope-note"/.test(HTML));
check("the note is hidden by default",
      /id="global-scope-note"[^>]*style="display:none"/.test(HTML),
      "it must only appear on global tabs");
check("the note is shown on global tabs",
      /global-scope-note[\s\S]{0,200}?display = global \? "" : "none"/.test(HTML));
check("the note is translated in both languages",
      /"scope\.global":\s*\{[\s\S]{0,400}?en:\s*"[\s\S]{0,300}?de:\s*"/.test(HTML));

// --- the stale tab key found on the way --------------------------------
// The redesign renamed "widgets" to "content"; the layout-preview
// re-render still tested for the old key, so it never fired.
check("the layout preview re-render uses the current tab key",
      /if \(key === "content" && typeof renderLayoutPreview/.test(HTML),
      'a stale "widgets" here means the preview keeps its 0x0 layout');

console.error("\n" + "=".repeat(68));
console.error(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
