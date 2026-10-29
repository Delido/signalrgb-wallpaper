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
// The first fix hid the strip on those tabs and left it where it was,
// above everything. That was the wrong fix — "find ich blöd gelöst" —
// because chrome that appears and disappears is a workaround, not a
// structure, and the strip still claimed to scope the whole page.
//
// The strip now lives inside the app shell, below the section nav and
// above the cards: pick a section, then a screen, and only where a
// screen is a real dimension of the settings below. Hiding it then
// reads as "this section has no screens" rather than as a glitch. So
// this suite pins the ordering, not just the visibility.
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
// Brace-matched rather than bounded by a character count: a {0,300}
// window broke the moment a comment was added at the top of the
// function, reporting a missing call that was still right there.
{
  const _at = HTML.indexOf("function activateSectionTab(key");
  const _end = HTML.indexOf("\nfunction ", _at + 10);
  const _fn = _at === -1 ? "" : HTML.slice(_at, _end === -1 ? _at + 3000 : _end);
  check("it is called from activateSectionTab",
        /_applyScreenScopeChrome\(key\)/.test(_fn),
        "declaring it without calling it changes nothing");
}
check("it hides the screen tab strip",
      /getElementById\("tabs"\)[\s\S]{0,200}?display = GLOBAL_TABS\.has\(key\) \? "none" : ""/
        .test(HTML),
      "the strip is the only chrome that has to react to the tab");

// --- structure, not just visibility -----------------------------------
// beta.22 hid the strip where it did not belong but left it above
// everything, so it flickered away as chrome. beta.23 moved it into the
// main column below the section nav: sections first, then a screen, and
// only where a screen is a real dimension of the settings below.
//
// Ordering is what makes the hiding read as "this section has no
// screens" rather than as a glitch, so it is worth pinning.
const iShell = HTML.indexOf('<div class="app-shell">');
const iSectionNav = HTML.indexOf('<nav id="section-tabs"');
const iScreenStrip = HTML.indexOf('<nav class="tabs" id="tabs">');
const iMain = HTML.indexOf('<main data-active-tab');

check("the screen strip is inside the app shell",
      iScreenStrip > iShell && iShell > 0,
      "above the shell it is page chrome, not part of a section");
check("the section nav comes before the screen strip",
      iSectionNav > 0 && iSectionNav < iScreenStrip,
      "picking a section has to come first");
check("the screen strip comes before the cards",
      iScreenStrip < iMain);
// v2.7.0-beta.1: the strip is now the top bar of that column (a
// view bar), still above the cards and right of the nav.
check("the strip sits in the main column's top bar",
      /<div class="shell-main">\s*<header>[\s\S]{0,600}?<nav class="tabs" id="tabs">/.test(HTML),
      "it must sit over the cards it applies to, not beside the nav");

// The old scope note belonged to the workaround and should be gone —
// leaving it would mean two mechanisms explaining the same thing.
check("the beta.22 scope note is gone",
      !/id="global-scope-note"/.test(HTML),
      "the structure explains itself now; the note was the workaround");

// The sidebar's sticky offset allowed for a screen-picker band above
// the shell. That band moved, so the offset had to shrink or the nav
// floats with a gap under the header.
// Every #section-tabs rule has to use the smaller offset: the two have
// equal specificity, so leaving a stale 100px behind means the winner
// depends on source order rather than on intent.
const stickyOffsets = [...HTML.matchAll(/#section-tabs \{[\s\S]*?top:\s*(\d+)px/g)]
  .map(m => Number(m[1]));
check("sidebar sticky offsets were updated for the new layout",
      stickyOffsets.length > 0 && stickyOffsets.every(v => v < 100),
      `offsets: ${stickyOffsets.join(", ")} — 100px allowed for the old band`);

// --- both navigations must survive scrolling ---------------------------
// Moving the strip into the page dropped the sticky positioning it had
// as page chrome, so it scrolled away while the section nav beside it
// stayed put. Reported as "die beiden Tabs sollten auch sichtbar sein
// wenn man runter scrollt".
const tabsRule = HTML.match(/(?<![\w-])\.tabs\s*\{([^}]*)\}/);
check(".tabs rule found", !!tabsRule);
if (tabsRule) {
  check("the screen strip is sticky",
        /position:\s*sticky/.test(tabsRule[1]),
        "it scrolls out of reach otherwise");
  const top = tabsRule[1].match(/top:\s*(\d+)px/);
  check("the screen strip has a sticky offset", !!top, tabsRule[1].trim());
  // Both navs clear the same ~53px header, and they occupy different
  // columns, so they should use the same offset — a mismatch makes one
  // sit visibly lower than the other.
  const navTop = HTML.match(/#section-tabs \{[\s\S]*?top:\s*(\d+)px/);
  check("both navs use the same sticky offset",
        !!top && !!navTop && top[1] === navTop[1],
        `strip ${top && top[1]}px vs nav ${navTop && navTop[1]}px`);
  check("the screen strip has an opaque background",
        /background:\s*var\(--bg\)/.test(tabsRule[1]),
        "cards would show through while scrolling under it");
}

// sticky silently stops working if an ancestor clips or constrains the
// scroll container, and the failure is invisible in the markup.
for (const sel of [".app-shell", ".shell-main"]) {
  const rule = HTML.match(new RegExp(`(?<![\\w-])\\${sel}\\s*\\{([^}]*)\\}`));
  if (!rule) continue;
  check(`${sel} does not clip its children`,
        !/overflow(-y)?:\s*(hidden|auto|scroll)/.test(rule[1]),
        "an overflow ancestor kills position:sticky");
}

// --- the stale tab key found on the way --------------------------------
// The redesign renamed "widgets" to "content"; the layout-preview
// re-render still tested for the old key, so it never fired.
check("the layout preview re-render uses the current tab key",
      /if \(key === "content" && typeof renderLayoutPreview/.test(HTML),
      'a stale "widgets" here means the preview keeps its 0x0 layout');

// --- Connections is grouped by direction -------------------------------
// "Colour source per screen" decides what the wallpaper follows, and it
// sat third of seven collapsed blocks, between OpenRGB output and the
// OpenRGB SDK server — an input in the middle of the outputs, with
// nothing marking the difference. Reported as "der source per Screen ist
// einfach mitten in den Optionen und nicht sauber ersichtlich".
//
// The order carries the meaning here, so the order is what gets pinned.
{
  const cardAt = HTML.indexOf('id="card-integrations"');
  const card = HTML.slice(cardAt, HTML.indexOf("</section>", cardAt));

  const heads = [...card.matchAll(/<h3(?: class="(conn-group)")? data-i18n="([\w.]+)"/g)]
    .map(m => ({ group: !!m[1], key: m[2] }));
  check("Connections headings found", heads.length >= 8, `${heads.length}`);

  const groups = heads.filter(h => h.group).map(h => h.key);
  check("three group headings exist", groups.length === 3, groups.join(", "));
  check("groups run input, output, other",
        groups.join(",") === "conn.group.input,conn.group.output,conn.group.other",
        groups.join(","));

  // The colour source has to lead the input group, not sit among the
  // outputs.
  const inputAt = heads.findIndex(h => h.key === "conn.group.input");
  const firstAfterInput = heads[inputAt + 1];
  check("the colour source leads the input group",
        !!firstAfterInput && firstAfterInput.key === "sources.header",
        firstAfterInput ? firstAfterInput.key : "nothing follows the heading");

  // And before every output block — that is the whole point of the move.
  const order = heads.filter(h => !h.group).map(h => h.key);
  const iSources = order.indexOf("sources.header");
  check("the colour source is present", iSources >= 0, order.join(" > "));
  for (const out of ["openrgb.header", "openrgb_sdk.header",
                     "sacn.header", "mqtt.header"]) {
    check(`${out} comes after the colour source`,
          iSources >= 0 && order.indexOf(out) > iSources, order.join(" > "));
  }

  for (const key of ["conn.group.input", "conn.group.output", "conn.group.other"]) {
    const esc = key.replace(/\./g, "\\.");
    const entry = HTML.match(new RegExp(`"${esc}":\\s*\\{[\\s\\S]{0,240}?\\}`));
    check(`${key} is translated in both languages`,
          !!entry && /en:\s*"/.test(entry[0]) && /de:\s*"/.test(entry[0]));
  }

  // Moving seven blocks is the same cut that tore a <summary> in half in
  // beta.22, so the pairing and the control count are checked here too.
  const dOpen = (card.match(/<details\b/g) || []).length;
  const dClose = (card.match(/<\/details>/g) || []).length;
  check("details tags stayed balanced after the reorder",
        dOpen === dClose && dOpen === 7, `${dOpen}/${dClose}`);
  const sOpen = (card.match(/<summary\b/g) || []).length;
  const sClose = (card.match(/<\/summary>/g) || []).length;
  check("summary tags stayed balanced", sOpen === sClose && sOpen === 7,
        `${sOpen}/${sClose}`);
  const ctrls = (card.match(/<(?:input|select|button)\b[^>]*id="[\w-]+"/g) || []).length;
  check("no control was lost in the move", ctrls === 24, `${ctrls}, expected 24`);
}

// --- sticky navs must not be scrolled through -------------------------
// A sticky element with no background and no z-index still sticks, but
// the cards scroll straight over it. The sidebar rule that ships (the
// last #section-tabs block, overriding the horizontal-band defaults
// further up) dropped both, so card headings appeared on top of the
// sidebar, the screen strip and the page header. Reported as
// "kattegorie Ueberschriften ueberblenden auch die Screens oder auch
// den header".
//
// CSS here has no cascade resolution, so take the LAST matching rule —
// which is what the browser does for equal specificity, and is exactly
// the rule that was wrong.
{
  const cssEnd = HTML.indexOf("</style>");
  // @media blocks are stripped: the narrow-viewport override for .tabs
  // only adjusts padding, and treating it as "the last rule" made this
  // report a correctly positioned bar as having no position at all.
  const CSS = HTML.slice(0, cssEnd > 0 ? cssEnd : HTML.length)
    .replace(/@media[^{]*\{(?:[^{}]|\{[^{}]*\})*\}/g, "");

  const lastRule = (sel) => {
    const esc = sel.replace(/[.#]/g, (c) => "\\" + c);
    const all = [...CSS.matchAll(new RegExp(`${esc}\\s*\\{([^}]*)\\}`, "g"))];
    return all.length ? all[all.length - 1][1] : null;
  };
  const prop = (body, name) => {
    if (!body) return null;
    const m = body.match(new RegExp(`(?:^|;|\\s)${name}:\\s*([^;]+)`));
    return m ? m[1].trim() : null;
  };

  for (const sel of ["#section-tabs", ".tabs"]) {
    const body = lastRule(sel);
    check(`${sel} rule found`, !!body);
    if (!body) continue;
    check(`${sel} is sticky`, /sticky/.test(prop(body, "position") || ""),
          prop(body, "position") || "no position");
    // Opaque, or the page shows through a bar that is supposed to cover
    // it. `transparent` is the specific value that shipped.
    const bg = prop(body, "background");
    check(`${sel} has an opaque background`,
          !!bg && !/transparent|none/.test(bg), bg || "no background");
    // Without a z-index a sticky element sits in the normal flow and
    // later content paints over it.
    const z = prop(body, "z-index");
    check(`${sel} declares a z-index`, !!z, "cards paint over it otherwise");
    if (z) {
      check(`${sel} sits below the page header`, Number(z) < 10,
            `z-index ${z}, header is 10`);
    }
  }

  // Both navs occupy the same band and must not fight each other.
  const zNav = prop(lastRule("#section-tabs"), "z-index");
  const zStrip = prop(lastRule(".tabs"), "z-index");
  check("both navs share the same layer", zNav === zStrip,
        `sidebar ${zNav} vs strip ${zStrip}`);
}

// --- card content must not paint over the navs ------------------------
// The sticky navs carry z-index 8, which only wins against
// non-positioned content. `main section.card > header.section-head` is
// position:relative (it anchors the ::before accent bar) with no
// z-index, and a positioned element paints above them regardless —
// they sit earlier in the document. Card headings therefore slid over
// the section list, the screen tabs and the page header while
// scrolling. Reported twice, the second time after a fix that only
// addressed the sidebar's transparency: "kattegorie Ueberschriften
// ueberblenden auch die Screens oder auch den header" and then "ueber
// screens das gleiche".
{
  const cssEnd2 = HTML.indexOf("</style>");
  const RAW = HTML.slice(0, cssEnd2 > 0 ? cssEnd2 : HTML.length)
    .replace(/@media[^{]*\{(?:[^{}]|\{[^{}]*\})*\}/g, "")
    .replace(/\/\*[\s\S]*?\*\//g, "");

  const headRule = [...RAW.matchAll(
    /main section\.card > header\.section-head\s*\{([^}]*)\}/g)].pop();
  check("the card-heading rule was found", !!headRule);
  if (headRule) {
    const body = headRule[1];
    const z = (body.match(/z-index:\s*([^;]+)/) || [])[1];
    check("the card heading declares a z-index", !!z,
          "positioned content without one paints over the sticky navs");
    if (z) {
      check("the card heading sits below the navs", Number(z.trim()) < 8,
            `z-index ${z.trim()}, navs are 8`);
    }
  }

  // Same trap anywhere else inside the cards: anything positioned with
  // no z-index will climb over the navs the moment it scrolls past.
  const offenders = [];
  for (const m of RAW.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    const sel = m[1].replace(/\s+/g, " ").trim();
    if (!/card|^main /.test(sel)) continue;
    if (!/position:\s*(relative|absolute)/.test(m[2])) continue;
    if (/z-index:/.test(m[2])) continue;
    offenders.push(sel);
  }
  check("no positioned card element is missing a z-index",
        offenders.length === 0, offenders.slice(0, 4).join(" | "));
}

// -- v2.5.2-beta.4: every reachable tab key must show something ------
//
// Reported as "wenn ich auf das hintergrundbild klicke, kommt ein
// hauch von nix": the background thumbnail called
// activateSectionTab("library"), a tab removed in the v2.5.0 redesign.
//
// The card CSS is a WHITELIST -- `main[data-active-tab] section.card`
// hides everything and only the four known values switch anything back
// on -- so an unrecognised key blanks the whole page. Silently: no
// console error, no visual clue, just an empty Configurator.
//
// LEGACY_TAB_ALIASES existed and even mapped library -> appearance, but
// only the startup path consulted it. In-page callers went straight
// through.
{
  console.error("\nno tab key can blank the page");

  // Scoped to the SECTION_TABS literal: `key: "..."` is a common shape
  // and a whole-file match picked up every widget option in the file.
  const stAt = HTML.indexOf("const SECTION_TABS = [");
  const stBlock = HTML.slice(stAt, HTML.indexOf("];", stAt));
  const tabKeys = [...stBlock.matchAll(/key:\s*"(\w+)"/g)].map((m) => m[1]);
  const aliases = {};
  const am = /LEGACY_TAB_ALIASES = \{([\s\S]*?)\}/.exec(HTML);
  if (am) for (const m of am[1].matchAll(/(\w+):\s*"(\w+)"/g)) aliases[m[1]] = m[2];
  // The CSS whitelist, read from the stylesheet rather than restated.
  const shown = new Set(
    [...HTML.matchAll(/main\[data-active-tab="(\w+)"\]/g)].map((m) => m[1]));

  check("the tab keys were parsed", tabKeys.length >= 4, tabKeys.join(","));
  check("the CSS whitelist was parsed", shown.size >= 4, [...shown].join(","));
  check("every declared tab has a CSS rule that shows its cards",
        tabKeys.every((k) => shown.has(k)),
        tabKeys.filter((k) => !shown.has(k)).join(",") + " would show nothing");

  // Every literal key passed to activateSectionTab in the page has to
  // survive the alias pass and land on something visible. This is the
  // reported bug, generalised to any caller.
  const calls = [...HTML.matchAll(/activateSectionTab\("(\w+)"\)/g)].map((m) => m[1]);
  check("literal activateSectionTab calls were found", calls.length > 0,
        "if this finds none the next check proves nothing");
  const dead = calls.filter((k) => !shown.has(aliases[k] || k));
  check("no caller asks for a tab that shows nothing",
        dead.length === 0,
        dead.join(",") + " resolves to no visible card");

  // And the resolution has to happen inside activateSectionTab, not
  // only at startup -- that gap is what made a mapped alias useless.
  const fnAt = HTML.indexOf("function activateSectionTab(key");
  const fnEnd = HTML.indexOf("\nfunction ", fnAt + 10);
  const fn = fnAt === -1 ? "" : HTML.slice(fnAt, fnEnd === -1 ? fnAt + 3000 : fnEnd);
  check("activateSectionTab was located", fn.length > 200);
  check("it resolves legacy aliases itself",
        /LEGACY_TAB_ALIASES\[key\]/.test(fn),
        "resolving only at startup leaves in-page callers broken");
  check("it falls back for a wholly unknown key",
        /SECTION_TABS\.some\([\s\S]{0,60}?key = "appearance"/.test(fn),
        "an unknown key must not hide every card");
  // Both guards must run BEFORE the attribute is written, or the page
  // is already blank by the time they execute.
  const aliasAt = fn.indexOf("LEGACY_TAB_ALIASES[key]");
  const writeAt = fn.indexOf("dataset.activeTab = key");
  check("the key is sanitised before it reaches the DOM",
        aliasAt !== -1 && writeAt !== -1 && aliasAt < writeAt,
        `alias\${aliasAt} write\${writeAt}`);
}

console.error("\n" + "=".repeat(68));
console.error(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
