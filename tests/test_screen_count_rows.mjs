// Per-screen lists must have one row per screen.
//
// WHY THIS EXISTS
//
// Four places rendered per-screen controls from
// `(settings && settings.screenCount) || 1`. That field does not exist:
// the bridge sends screenCount *beside* the settings payload
// (`{type:"settings", data:{…}, screenCount:2}`) and the Configurator
// assigns `settings = msg.data`, so `settings.screenCount` is always
// undefined and every one of them fell back to 1.
//
// On a two-screen setup the colour-source list, both sACN universe
// lists and the OpenRGB source picker each showed a single row. Nothing
// errored — the `|| 1` fallback made a wrong answer look like a
// deliberate default, which is why it survived several releases.
// Reported as "müssten hier nicht 2 Screens sein?".
//
// The module-level `screenCount` is the reliable value: applyScreenCount()
// updates it on every settings push.
//
// This suite runs the real renderer in a sandbox and counts the rows it
// produces, rather than grepping for the expression — a future site
// could reintroduce the bug with different wording, and a row count is
// the thing that actually matters.

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

console.error("\nPer-screen row counts\n" + "=".repeat(68));

const src = [...HTML.replace(/<!--[\s\S]*?-->/g, "")
  .matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).sort((a, b) => b.length - a.length)[0];

// --- nobody may read the field that does not exist ---------------------
// Comments mentioning it are fine; a live read is not.
const liveReads = [...src.matchAll(/^[^/\n]*settings\s*&&\s*settings\.screenCount/gm)];
check("no live read of settings.screenCount", liveReads.length === 0,
      liveReads.map(m => m[0].trim()).join(" | "));

// And the bridge must still send it beside the payload, not inside it —
// if that ever changes, the fix above is the thing that breaks.
const BRIDGE = readFileSync(
  join(HERE, "..", "wallpaper_bridge", "bridge.py"), "utf8");
// There are two places that emit a {"type":"settings"} message — one on
// connect, one on every update — and BOTH must carry screenCount. A
// single-site check passes while the other has lost it, which would
// leave the count stale after the first push.
// Locate each site by its opening marker and take a fixed window from
// there. Matching through to a closing brace is what kept failing: the
// two sites differ in indentation and length, so any single stop token
// caught one and missed the other.
const settingsMsgs = [...BRIDGE.matchAll(/"type":\s*"settings"/g)]
  .map(m => BRIDGE.slice(m.index, m.index + 500));
check("both settings-message sites found", settingsMsgs.length === 2,
      `found ${settingsMsgs.length}`);
for (let i = 0; i < settingsMsgs.length; i++) {
  check(`settings message #${i + 1} carries screenCount`,
        /"screenCount":/.test(settingsMsgs[i]),
        "without it applyScreenCount never runs for this push");
  check(`settings message #${i + 1} keeps screenCount beside data`,
        /"data":\s*settings,[\s\S]{0,200}?"screenCount":/.test(settingsMsgs[i]),
        "if it moved into data, settings.screenCount would become valid again");
}
check("the Configurator assigns settings = msg.data",
      /settings = msg\.data;/.test(src));
check("applyScreenCount is called from the settings push",
      /applyScreenCount\(msg\.screenCount\)/.test(src));

// --- run the renderer --------------------------------------------------
const body = (src.match(/function _renderSourcesList\(\)\s*\{[\s\S]*?\n  \}/) || [])[0];
check("_renderSourcesList extracted", !!body);

function renderRows(globalCount, settingsObj) {
  const rows = [];
  const stubEl = () => ({
    className: "", style: { cssText: "" }, id: "",
    textContent: "", value: "", innerHTML: "",
    appendChild() {}, addEventListener() {}, setAttribute() {},
  });
  const wrap = { innerHTML: "", appendChild: (r) => rows.push(r) };
  const ctx = {
    document: {
      getElementById: (id) => (id === "sources-list" ? wrap : null),
      createElement: () => stubEl(),
    },
    screenCount: globalCount,
    settings: settingsObj,
    bridgeState: { sources: {} },
    t: (k) => k,
    console: { log() {}, warn() {}, error() {} },
    _pushSources() {},
  };
  vm.runInNewContext(body + "\n_renderSourcesList();", ctx, { timeout: 5000 });
  return rows.length;
}

if (body) {
  // The realistic case: settings is msg.data and carries no screenCount.
  check("two screens produce two rows", renderRows(2, { bgImage: "x" }) === 2,
        `got ${renderRows(2, { bgImage: "x" })}`);
  check("one screen produces one row", renderRows(1, {}) === 1);
  check("four screens produce four rows", renderRows(4, {}) === 4,
        `got ${renderRows(4, {})}`);
  // A stale settings.screenCount must not win over the live global.
  check("a stale settings.screenCount does not override the global",
        renderRows(3, { screenCount: 1 }) === 3,
        `got ${renderRows(3, { screenCount: 1 })}`);
  // Guard the lower bound: 0 or undefined must still render one row
  // rather than an empty list.
  check("a zero count still renders one row", renderRows(0, {}) === 1);
}

console.error("\n" + "=".repeat(68));
console.error(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
